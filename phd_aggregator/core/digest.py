"""core.digest — the weekly recommendation digest (Sprint 07, Track A2).

Follows the contract in ``prompts/05_OpenCode_Email_Service.md`` exactly:

- only opportunities with ``match_score > 0.85``
- maximum 5 positions
- maximum 5 supervisors (when enabled)
- every item includes *why matched* (the deterministic explanation), the
  *deadline*, *funding*, and a *next action*

Selection is fully deterministic (score desc, then earliest deadline, then
title) and pure — no LLM, no network — so it is unit-testable with plain
profile + match fixtures. LLM personalization arrives in Sprint 09 and will
only rewrite the *text*, never the selection.

``build_digest`` returns ``{subject, html, text}`` ready for
:func:`core.email.send_email`.
"""

from __future__ import annotations

import logging
import os
from core.env import env_flag
from datetime import datetime
from typing import Optional

# The minimum score an opportunity must reach to appear in a digest
# (prompts/05: "only send opportunities with score > 85" → 0.85 on 0-1).
DIGEST_MIN_SCORE = 0.85
DIGEST_MAX_POSITIONS = 5
DIGEST_MAX_SUPERVISORS = 5

log = logging.getLogger("phd_aggregator")


def digest_llm_enabled() -> bool:
    """Feature toggle for the digest's LLM reason rewriting (C1).

    Selection stays deterministic regardless; this only controls the optional
    plain-language rewrite of the 'why this fits' text. Defaults to ON so the
    feature is live once an LLM provider is configured."""
    return env_flag("DIGEST_LLM_ENABLED", default=True, falsy=("0", "false", "", "no"))


def dashboard_url() -> str:
    """The public dashboard origin (env-overridable for staging/prod)."""
    return os.environ.get(
        "DASHBOARD_URL", "https://dashboard.example.com").rstrip("/")


def _fmt_date(value) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y")
    return str(value)


def escape(text) -> str:
    """Minimal HTML escaping for injected strings."""
    if text is None:
        return ""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _parse_deadline(value):
    """Parse a deadline into a comparable date, or None when unknown.

    Deadlines arrive as ``datetime`` objects (SQLite/postgres) or as the
    ISO-ish strings the ingestion layer wrote ("2026-08-31",
    "2026-8-1", "2026-08-31 12:00:00"). ``fromisoformat`` (3.11+) covers the
    ISO family including non-padded months/days; a few strptime formats cover
    display strings. Unknown values sort last so sorting never mixes str and
    dates.
    """
    if isinstance(value, datetime):
        return value.date()
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except (ValueError, TypeError):
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _pos_sort_key(item: dict):
    """Deterministic ordering: score desc, then earliest deadline, then title.

    Deadlines are parsed as real dates so sorting is chronological, not a
    lexicographic string compare ("2026-10-05" < "2026-09-01" for strings, but
    Sept 1 is genuinely earlier). Missing/unparseable deadlines (rolling) sort
    last among their score-tie group.
    """
    score = float(item.get("match_score") or 0.0)
    deadline = _parse_deadline(item.get("deadline"))
    if deadline is None:
        deadline_key = (1, 0)  # rolling / unknown -> after every dated item
    else:
        deadline_key = (0, deadline.toordinal())
    title = (item.get("title") or "").lower()
    return (round(-score, 6), deadline_key, title)


def select_top_positions(matches: Optional[list],
                         limit: int = DIGEST_MAX_POSITIONS,
                         min_score: float = DIGEST_MIN_SCORE) -> list:
    """Top-``limit`` matches with ``match_score > min_score``, deterministic.

    ``matches`` are opportunity dicts enriched with ``match_score`` /
    ``match_explanation`` (as produced by the /api/matches layer). Returns a
    fresh list; never mutates its input.
    """
    if not matches:
        return []
    eligible = [m for m in matches
                if m and (m.get("match_score") is not None)
                and float(m["match_score"]) > min_score]
    eligible.sort(key=_pos_sort_key)
    return eligible[:limit]


def select_supervisors(supervisors: Optional[list],
                       limit: int = DIGEST_MAX_SUPERVISORS) -> list:
    """Top ``limit`` supervisors by ``fit_score`` desc, then name; capped."""
    if not supervisors:
        return []
    rows = [s for s in supervisors if s]
    rows.sort(key=lambda s: (round(-(float(s.get("fit_score") or 0.0)), 6),
                             (s.get("name") or "").lower()))
    return rows[:limit]


def _next_step(p: dict) -> str:
    """Deterministic 'next action': apply-by when a deadline exists, else a
    pointer to the posting."""
    deadline = _fmt_date(p.get("deadline"))
    if deadline:
        return f"Apply by {deadline}"
    url = p.get("url")
    if url:
        return "Review the posting and prepare your application"
    return "Add this to your shortlist and prepare your application"


def rewrite_reasons(items: Optional[list], llm) -> list[Optional[str]]:
    """LLM rewrite of the top items' explanations into one plain sentence each.

    A single batched completion call returns a JSON list aligned with ``items``
    (keyed by original index). Each element is the rewritten reason, or None
    when that item has no rewrite — the caller falls back to the deterministic
    explanation. On ANY LLM failure the whole batch degrades to ``[None]*n``:
    the digest must never fail because the LLM did. Pure text — the selection
    and scoring are untouched.
    """
    if not items:
        return []
    listing = "\n".join(
        f"[{i}] title: {p.get('title') or '?'}\n"
        f"    explanation: {p.get('match_explanation') or ''}"
        for i, p in enumerate(items))
    prompt = (
        "You are helping a researcher understand why positions fit their "
        "profile. Rewrite each structured explanation below into ONE "
        "plain-language sentence addressed to the researcher, starting with "
        "'This fits you because …'. Stay strictly within the given facts — "
        "never add skills, locations or claims not in the explanation.\n\n"
        f"{listing}\n\n"
        'Return a JSON object {"reasons": [{"index": 0, '
        '"reason": "…"}, ...]} with exactly one entry per item, using the '
        "original index numbers.\n"
    )
    try:
        from core.llm import extract_json_block
        parsed = extract_json_block(llm.complete(prompt))
        reasons = parsed.get("reasons", []) if isinstance(parsed, dict) else []
        by_index: dict[int, str] = {}
        for r in reasons:
            if isinstance(r, dict) and isinstance(r.get("index"), int):
                text = str(r.get("reason") or "").strip()
                if text:
                    by_index[r["index"]] = text
        return [by_index.get(i) for i in range(len(items))]
    except Exception as exc:
        log.warning("digest reason rewrite failed (%s) — using deterministic "
                    "explanations", exc)
        return [None] * len(items)


def _pos_html(i: int, p: dict) -> str:
    title = p.get("title") or "Untitled position"
    inst = p.get("institution") or "—"
    country = p.get("country") or "—"
    funding = (p.get("funding_status") or p.get("funding_requirement")
               or "check posting")
    why = (p.get("why_rewritten") or p.get("match_explanation")
           or "").strip() or "No explanation stored."
    url = p.get("url")
    title_html = (f"<a href='{escape(url)}' style='color:#1a6fb5;"
                  f"text-decoration:none;'>{escape(title)}</a>"
                  if url else escape(title))
    return (
        f"<tr><td style='padding:8px 0;border-bottom:1px solid #eee;'>"
        f"<div style='font-size:14px;font-weight:600;'>{i}. {title_html}</div>"
        f"<div style='color:#666;font-size:12px;'>{escape(inst)} — "
        f"{escape(country)} &nbsp;|&nbsp; <b>{escape(funding)}</b></div>"
        f"<div style='color:#444;font-size:13px;margin-top:4px;'>"
        f"<i>Why this fits:</i> {escape(why)}</div>"
        f"<div style='color:#333;font-size:13px;margin-top:4px;'>"
        f"<b>Deadline:</b> {escape(_fmt_date(p.get('deadline')) or 'rolling')}"
        f" &nbsp;·&nbsp; <b>Next step:</b> {escape(_next_step(p))}"
        f"</div></td></tr>")


def _sup_html(i: int, s: dict) -> str:
    name = escape(s.get("name") or "—")
    inst = escape(s.get("institution") or "—")
    country = escape(s.get("country") or "—")
    topics = escape(", ".join(s.get("topics") or [])[:160]) or "no topics listed"
    profile = s.get("profile_url")
    name_html = (f"<a href='{escape(profile)}' style='color:#1a6fb5;"
                 f"text-decoration:none;'>{name}</a>" if profile else name)
    return (
        f"<tr><td style='padding:8px 0;border-bottom:1px solid #eee;'>"
        f"<b>{i}. {name_html}</b> — {inst} ({country})<br/>"
        f"<span style='color:#666;font-size:12px;'>topics: {topics}</span>"
        f"{'<br/><a href=' + escape(profile) + "' style='font-size:12px;'>"
        f"profile</a>" if profile else ""}</td></tr>")


def _plain_text(profile, pos, sup) -> str:
    domain = profile.domain or "your field"
    lines = [f"Your weekly career digest ({domain})", "=" * 40, ""]
    if pos:
        lines.append("POSITIONS (why, deadline, funding, next step)")
        for i, p in enumerate(pos, 1):
            lines.append(f"{i}. {p.get('title', '')}")
            why = p.get("why_rewritten") or p.get("match_explanation")
            lines.append(f"   why: {why or '—'}")
            if p.get("deadline"):
                lines.append(f"   deadline: {_fmt_date(p['deadline'])}")
            funding = p.get("funding_status") or p.get("funding_requirement")
            if funding:
                lines.append(f"   funding: {funding}")
            lines.append(f"   next step: {_next_step(p)}")
            lines.append("")
    else:
        lines.append("No matching positions this week.")
    if sup:
        lines.append("SUPERVISORS WORTH CONTACTING")
        for i, s in enumerate(sup, 1):
            lines.append(f"{i}. {s.get('name', '')} — "
                         f"{s.get('institution', '')}")
        lines.append("")
    lines.append("Manage your preferences and unsubscribe at the dashboard: "
                 + dashboard_url() + "/settings")
    return "\n".join(lines)


def build_digest(profile,
                 positions: Optional[list] = None,
                 supervisors: Optional[list] = None,
                 include_supervisors: bool = False,
                 llm=None) -> dict:
    """Render a weekly digest email.

    ``positions``: match dicts with at least ``title``, ``match_score``,
    ``match_explanation`` (deadline/funding optional).
    ``supervisors``: supervisor dicts with ``fit_score`` when included.
    ``llm``: optional LLMRouter for the v2 reason rewrite. When provided AND
    ``digest_llm_enabled()``, the top positions' explanations are rewritten to
    one plain sentence each, with a deterministic fallback on any failure.
    Selection and scoring are never affected by the LLM.
    Returns ``{subject, html, text}`` — deterministic except for the optional
    rewrite, and fully offline (LLM failures degrade, never raise).
    """
    domain = profile.domain or "your field"
    subfield = profile.subfield
    subject = (f"Your weekly career digest ({domain}/{subfield})"
               if subfield else f"Your weekly career digest ({domain})")

    pos = select_top_positions(positions)
    if llm is not None and digest_llm_enabled():
        reasons = rewrite_reasons(pos, llm)
        pos = [dict(p, why_rewritten=r) if r else dict(p)
               for p, r in zip(pos, reasons)]
    sup = select_supervisors(supervisors) if include_supervisors else []

    body: list[str] = [
        "<div style='font-family:Arial,Helvetica,sans-serif;max-width:640px;"
        "margin:0 auto;'>",
        "<h2 style='margin-bottom:4px;'>Your weekly career digest</h2>",
        f"<p style='color:#666;'>Matched for <b>{escape(domain)}</b>"
        f"{' / ' + escape(subfield) if subfield else ''} — the highest-fit "
        "roles from the latest scan.</p>",
    ]
    if pos:
        body.append(
            "<h3>Top positions</h3>"
            "<table style='border-collapse:collapse;width:100%;font-size:14px;'>"
            + "".join(_pos_html(i, p) for i, p in enumerate(pos, 1))
            + "</table>")
    else:
        body.append(
            "<p><b>No matching positions this week.</b> Check back after the "
            "next scan, or widen your countries in Settings.</p>")

    if sup:
        body.append(
            "<h3>Supervisors worth contacting</h3>"
            "<table style='border-collapse:collapse;width:100%;'>"
            + "".join(_sup_html(i, s) for i, s in enumerate(sup, 1))
            + "</table>")

    body.append(
        "<p style='color:#888;font-size:12px;margin-top:24px;'>"
        f"Change your settings or unsubscribe "
        f"<a href='{dashboard_url()}/settings'>here</a>. "
        "Career Intelligence Kit.</p></div>")

    return {
        "subject": subject,
        "html": "".join(body),
        "text": _plain_text(profile, pos, sup),
    }
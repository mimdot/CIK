"""pipeline.freshness — state persistence + the freshness layer (migration
Step 7, part 1). Extracted verbatim from the original monolith.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Optional

from core.config import Config
from core.utils import _key_text, normalize_url
from pipeline.parse_page import extract_page_date

log = logging.getLogger("astra")


# -----------------------------------------------------------------------------
# FRESHNESS LAYER — undated posts must not survive forever
#
# Effective-date priority: (1) future deadline (always keeps the post),
# (2) posted_date, (3) first-seen timestamp persisted in the state file from
# the run that discovered the URL, (4) a date read off the page itself
# (JSON-LD dateModified, article:published_time, a visible "Posted on ..."
# line). A record with NO future deadline whose effective date is older than
# cfg.max_age_days is dropped as stale. A truly dateless post is kept on
# FIRST discovery, then its first-seen date ages it out on later runs.
# -----------------------------------------------------------------------------
_FRESHNESS_QUALITY = {"deadline": 4, "posted": 3, "page_date": 2,
                      "first_seen": 1, "undated_new": 0}


def load_state(cfg: Config) -> dict:
    """Read the local state file ({normalized url: {first_seen, last_seen}}
    plus seed-domain counters). Missing/corrupt file -> fresh state."""
    try:
        with open(cfg.state_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        if isinstance(state, dict):
            state.setdefault("urls", {})
            state.setdefault("seed_domains", {})
            return state
    except FileNotFoundError:
        pass
    except Exception as exc:
        log.warning("state file %s unreadable (%s) — starting fresh",
                    cfg.state_path, exc)
    return {"version": 1, "urls": {}, "seed_domains": {}}


def save_state(state: dict, cfg: Config, today: Optional[date] = None) -> None:
    """Persist state; prune URLs not seen for 2x the freshness window."""
    today = today or date.today()
    horizon = (today - timedelta(days=2 * max(cfg.max_age_days, 30))).isoformat()
    urls = state.get("urls", {})
    stale = [k for k, v in urls.items()
             if (v.get("last_seen") or v.get("first_seen") or "") < horizon]
    for k in stale:
        del urls[k]
    try:
        with open(cfg.state_path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=1, ensure_ascii=False)
        log.debug("state saved: %d urls (%d pruned) -> %s",
                  len(urls), len(stale), cfg.state_path)
    except Exception as exc:
        log.warning("could not write state file %s: %s", cfg.state_path, exc)




def apply_freshness(records: list[dict], cfg: Config, state: dict,
                    today: Optional[date] = None,
                    http: Optional["Http"] = None) -> list[dict]:
    """Stamp freshness/effective_date/age_days on every record, update the
    seen-state, and drop stale records. Logs a per-run breakdown."""
    today = today or date.today()
    today_iso = today.isoformat()
    urls_state = state.setdefault("urls", {})
    probes_left = cfg.max_page_date_probes if http is not None else 0
    kept: list[dict] = []
    stats = {"deadline": 0, "posted": 0, "first_seen": 0, "page_date": 0,
             "undated_new": 0, "dropped_stale": 0}

    for r in records:
        key = normalize_url(r.get("url")) or "t:" + _key_text(r.get("title"))
        entry = urls_state.get(key)
        prior_first_seen = entry.get("first_seen") if entry else None
        if entry is None:
            urls_state[key] = {"first_seen": today_iso, "last_seen": today_iso}
        else:
            entry["last_seen"] = today_iso

        deadline, posted = r.get("deadline"), r.get("posted_date")
        if deadline and deadline >= today_iso:
            freshness, effective = "deadline", deadline
        elif posted:
            freshness, effective = "posted", posted
        elif deadline:  # past deadline; only reachable with --include-expired
            freshness, effective = "deadline", deadline
        elif prior_first_seen and prior_first_seen < today_iso:
            freshness, effective = "first_seen", prior_first_seen
        else:
            # first encounter of a dateless post: weak last resort — try to
            # read a posted/updated date off the page itself
            freshness = effective = None
            if probes_left > 0 and r.get("url"):
                probes_left -= 1
                resp = http.get(r["url"])
                page_date = extract_page_date(resp.text) if resp is not None else None
                if page_date:
                    freshness, effective = "page_date", page_date
                    log.info("[freshness] read %s off the page for %s",
                             page_date, r.get("url"))
            if not freshness:
                freshness, effective = "undated_new", today_iso

        try:
            age = (today - date.fromisoformat(effective)).days
        except ValueError:
            age = 0
        r["freshness"] = freshness
        r["effective_date"] = effective
        r["age_days"] = max(age, 0)   # future deadline -> 0, not negative

        if freshness == "deadline" and effective >= today_iso:
            keep = True                       # future deadline always keeps
        elif freshness == "undated_new":
            keep = True                       # keep on first discovery
        elif freshness == "first_seen":
            keep = cfg.keep_undated_within_window and age <= cfg.max_age_days
        else:                                 # posted / page_date / past deadline
            keep = age <= cfg.max_age_days
        if keep:
            stats[freshness] += 1
            kept.append(r)
        else:
            stats["dropped_stale"] += 1
            if cfg.debug:
                log.debug("[freshness] stale (%s %s, %dd old): %s",
                          freshness, effective, age,
                          (r.get("title") or "")[:70])

    log.info("[freshness] kept: %d future-deadline, %d posted-date, "
             "%d first-seen, %d page-date, %d undated-new | DROPPED stale "
             "(>%dd): %d", stats["deadline"], stats["posted"],
             stats["first_seen"], stats["page_date"], stats["undated_new"],
             cfg.max_age_days, stats["dropped_stale"])
    return kept

"""core.feedback_intel — match-feedback intelligence (Sprint 09, Track B2).

Answers four ops questions from the ``match_feedback`` rows:

  1. overall helpful-rate + volume (``summary``);
  2. is low-confidence matching the problem? (``score_brackets`` groups
     helpful-rate by the match's overall-score band — an unhelpful-heavy
     low band means the ranking itself is the issue);
  3. which data sources produce weak matches? (``source_breakdown``);
  4. what are users actually complaining about? (``comment_focus`` turns
     negative comments into keyword hits + a short comment sample list).

Pure read-only aggregates over the session; the admin endpoint exposes them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.models import Match, MatchFeedback, Opportunity

SCORE_BRACKETS = ["0-20", "20-40", "40-60", "60-80", "80-100"]

KEYWORDS = [
    "funding", "salary", "stipend", "visa", "english", "relocation",
    "location", "deadline", "skills", "requirements", "competition",
    "too far", "not remote", "not relevant", "wrong field", "senior",
    "junior", "experience", "rejected", "mismatch", "no",
]


def _rate(helpful: int, total: int) -> Optional[float]:
    return round(helpful / total, 3) if total else None


def _bracket(score: Optional[float]) -> str:
    s = score if score is not None else 0.0
    if s < 20:
        return "0-20"
    if s < 40:
        return "20-40"
    if s < 60:
        return "40-60"
    if s < 80:
        return "60-80"
    return "80-100"


def summary(session: Session) -> Dict[str, Any]:
    """Overall helpful-rate + volume."""
    total = session.scalar(
        select(func.count()).select_from(MatchFeedback)) or 0
    helpful = session.scalar(
        select(func.count()).select_from(MatchFeedback)
        .where(MatchFeedback.helpful.is_(True))) or 0
    unhelpful = session.scalar(
        select(func.count()).select_from(MatchFeedback)
        .where(MatchFeedback.helpful.is_(False))) or 0
    return {"total": total, "helpful": helpful, "unhelpful": unhelpful,
            "rate": _rate(helpful, total)}


def score_brackets(session: Session) -> List[Dict[str, Any]]:
    """Helpful-rate per overall-score band over all feedback rows."""
    rows = session.execute(
        select(Match.overall_score, MatchFeedback.helpful)
        .select_from(MatchFeedback)
        .join(Match, Match.id == MatchFeedback.match_id)
    ).all()
    grouped: Dict[str, Dict[str, int]] = {"brackets": {}}
    buckets = grouped["brackets"]
    for score, helpful in rows:
        key = _bracket(score)
        g = buckets.setdefault(key, {"total": 0, "helpful": 0})
        g["total"] += 1
        g["helpful"] += 1 if helpful else 0
    out = []
    for key in SCORE_BRACKETS:
        g = buckets.get(key)
        if not g or not g["total"]:
            continue
        out.append({"key": key, "total": g["total"], "helpful": g["helpful"],
                    "rate": _rate(g["helpful"], g["total"])})
    return out


def source_breakdown(session: Session) -> List[Dict[str, Any]]:
    """Helpful-rate grouped by the source of the matched opportunity."""
    rows = session.execute(
        select(Opportunity.source, MatchFeedback.helpful)
        .select_from(MatchFeedback)
        .join(Match, Match.id == MatchFeedback.match_id)
        .join(Opportunity, Opportunity.id == Match.opportunity_id)
    ).all()
    groups: Dict[str, Dict[str, int]] = {}
    for source, helpful in rows:
        key = source or "unknown"
        g = groups.setdefault(key, {"total": 0, "helpful": 0})
        g["total"] += 1
        g["helpful"] += 1 if helpful else 0
    return [{"key": k, "total": g["total"], "helpful": g["helpful"],
             "rate": _rate(g["helpful"], g["total"])}
            for k, g in sorted(groups.items(), key=lambda kv: -kv[1]["total"])]


def comment_focus(session: Session, limit: int = 5) -> Dict[str, Any]:
    """Keyword hits + a few concrete negative comments for the admin UI."""
    rows = session.execute(
        select(MatchFeedback.comment, Match.overall_score,
               Opportunity.source)
        .select_from(MatchFeedback)
        .join(Match, Match.id == MatchFeedback.match_id)
        .join(Opportunity, Opportunity.id == Match.opportunity_id)
        .where(MatchFeedback.comment.isnot(None),
               MatchFeedback.comment != "")
    ).all()

    hits: Dict[str, int] = {}
    samples: List[Dict[str, Any]] = []
    for comment, score, source in rows:
        comment = (comment or "").strip()
        low = comment.lower()
        for kw in KEYWORDS:
            if kw in low:
                hits[kw] = hits.get(kw, 0) + 1
        samples.append({"comment": comment[:220],
                        "score": (score if score is not None else None),
                        "source": source})

    def _sort_key(s):
        return (s["score"] is not None, -((s["score"] or 0)))

    samples.sort(key=lambda s: (s["score"] is None, s["score"] is not None))
    samples = samples[:limit]
    top = sorted(hits.items(), key=lambda kv: -kv[1])[:10]
    return {"keywords": [{"keyword": k, "count": c} for k, c in top],
            "samples": samples}


def feedback_intel(session: Session) -> Dict[str, Any]:
    """Top-level aggregate used by the admin endpoint."""
    return {"summary": summary(session),
            "brackets": score_brackets(session),
            "sources": source_breakdown(session),
            "comments": comment_focus(session)}
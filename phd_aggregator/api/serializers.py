"""api.serializers — ORM row → plain-dict response shapes (Sprint 04).

The API returns plain dicts (no ORM objects leak out). JSON-as-text columns
are decoded back to lists here, mirroring what ``UserProfileRow.to_profile``
does for profiles.
"""

from __future__ import annotations

import json
from typing import Optional

from db.models import ApiKey, Bookmark, Opportunity, Supervisor


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def _json_list(value) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return []


def opportunity_out(opp: Opportunity) -> dict:
    return {
        "id": opp.id,
        "source": opp.source,
        "title": opp.title,
        "institution": opp.institution,
        "department": opp.department,
        "country": opp.country,
        "city": opp.city,
        "url": opp.url,
        "type": opp.type,
        "field": opp.field,
        "subfield": opp.subfield,
        "topics": _json_list(opp.topics),
        "deadline": _iso(opp.deadline),
        "posted_date": _iso(opp.posted_date),
        "effective_date": _iso(opp.effective_date),
        "freshness": opp.freshness,
        "relevance_score": opp.relevance_score,
        "short_description": opp.short_description,
        "position_type": opp.position_type,
        "is_new": opp.is_new,
        # WHY this row is here. The engine records the terms that matched, but
        # they stopped at the database — so the UI could never show the user
        # that their profile had done anything, which is most of the reason
        # "does my research profile even work?" had no answer.
        "matched_keywords": _json_list(opp.matched_keywords),
        "matched_anchors": _json_list(opp.matched_anchors),
    }


def supervisor_out(sup: Supervisor) -> dict:
    orcid = _orcid_from_url(sup.profile_url)
    return {
        "id": sup.id,
        "source": sup.source,
        "name": sup.name,
        "institution": sup.institution,
        "department": sup.department,
        "country": sup.country,
        "profile_url": sup.profile_url,
        "email": sup.email,
        "orcid": orcid,
        "topics": _json_list(sup.topics),
        "methods": _json_list(sup.methods),
        "recent_papers": _json_list(sup.recent_papers),
        "fit_score": sup.fit_score,
        "fit_explanation": sup.fit_explanation,
        "confidence": sup.confidence,
    }


def _orcid_from_url(url: Optional[str]) -> Optional[str]:
    """Extract the ORCID iD from an OpenAlex/ORCID profile URL, if any."""
    if not url:
        return None
    import re
    match = re.search(r"orcid\.org/(\d{4}-\d{4}-\d{4}-\d{3}[0-9X])", url)
    return match.group(1) if match else None


def bookmark_out(bm: Bookmark, opportunity: dict) -> dict:
    return {"id": bm.id, "opportunity_id": bm.opportunity_id,
            "created_at": _iso(bm.created_at),
            "opportunity": opportunity}


def api_key_out(key: ApiKey) -> dict:
    """API key row → response shape (never includes the raw key)."""
    return {
        "id": key.id,
        "name": key.name,
        "key_prefix": key.key_prefix,
        "scopes": _json_list(key.scopes),
        "quota_limit": key.quota_limit,
        "rate_limit": key.rate_limit,
        "last_used_at": _iso(key.last_used_at),
        "expires_at": _iso(key.expires_at),
        "revoked_at": _iso(key.revoked_at),
        "created_at": _iso(key.created_at),
    }

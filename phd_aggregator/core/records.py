"""core.records — normalized record factory + output schema.

Extracted verbatim from phd_aggregator.py (migration Step 2). Pure relocation:
no behavior, signature, or output changes.

COUPLING NOTE: :data:`MAX_DESC_CHARS` is imported from :mod:`core.config` at
module level rather than being a ``max_desc`` parameter on :func:`make_record`.
That mirrors the pre-migration monolith (a single module-level constant) and
keeps the signature identical — changing it to a parameter is a deliberate
post-migration refactor, out of scope for Step 2.
"""

from __future__ import annotations

from typing import Optional

from core.config import MAX_DESC_CHARS
from core.utils import (
    canonical_country,
    clean_oneline,
    clean_text,
    parse_date,
)

# Output schema (order used for CSV columns). `raw_location` is internal-only.
# freshness/effective_date/age_days come from the freshness layer: how the
# record's effective date was derived (deadline / posted / first_seen /
# page_date / undated_new) and how old it is.
OUTPUT_FIELDS = [
    "title", "institution", "country", "deadline", "posted_date",
    "effective_date", "age_days", "freshness", "url",
    "source", "relevance_score", "matched_anchors", "matched_keywords",
    "short_description", "position_type", "is_new",
    "match_score", "match_explanation",
]


def make_record(*, title=None, institution=None, country=None, deadline=None,
                posted_date=None, url=None, source=None, short_description=None,
                position_type=None, raw_location=None, country_hint=None,
                matched_keywords=None) -> dict:
    """Build a normalized record dict with every field present (defensive).

    NOTE for source authors: `short_description` is scored by the relevance
    engine — put the actual ad text there, and use `raw_location` for
    department/location strings that should inform country detection only.
    Pass `position_type="phd"` when the SOURCE guarantees the level (e.g. a
    PhD-only search facet); leave it None to let the classifier decide.
    `country` is the board-provided fallback; `country_hint` is an explicit
    location seen on the listing (beats both the board default AND free-text
    guessing in filter_records).
    """
    return {
        "title": clean_oneline(title),
        "institution": clean_oneline(institution),
        "country": canonical_country(country),
        "country_hint": canonical_country(country_hint),
        "deadline": parse_date(deadline),
        "posted_date": parse_date(posted_date),
        "url": (url.strip() if isinstance(url, str) and url.strip() else None),
        "source": source,
        "relevance_score": 0.0,
        "matched_anchors": [],
        "matched_keywords": list(matched_keywords) if matched_keywords else [],
        "short_description": clean_text(short_description, MAX_DESC_CHARS),
        "position_type": position_type,
        "raw_location": clean_oneline(raw_location),  # internal, dropped on write
        "is_new": False,
        "freshness": None,        # set by the freshness layer
        "effective_date": None,
        "age_days": None,
        "match_score": None,      # set by apply_profile_matching (Track C3)
        "match_explanation": None,
    }
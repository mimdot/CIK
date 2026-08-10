"""pipeline.dedupe — merge records that describe the same posting
(migration Step 7, part 2). Extracted verbatim from the original monolith.

Pass 1 merges on identical normalized URL; pass 2 on title+institution (the
same job posted on several boards).
"""

from __future__ import annotations

import logging
import re

from core.utils import dedupe_key, normalize_url
from pipeline.freshness import _FRESHNESS_QUALITY

log = logging.getLogger("phd_aggregator")


# -----------------------------------------------------------------------------
# Dedupe (merge sources + keywords on collision)
# -----------------------------------------------------------------------------
def _merge_into(base: dict, dup: dict) -> None:
    # union sources
    srcs = {s.strip() for s in re.split(r"[;,]", base.get("source") or "") if s.strip()}
    if dup.get("source"):
        srcs.add(dup["source"])
    base["source"] = "; ".join(sorted(srcs)) if srcs else base.get("source")
    # union matched keywords/anchors
    for f in ("matched_keywords", "matched_anchors"):
        merged = list(dict.fromkeys((base.get(f) or []) + (dup.get(f) or [])))
        base[f] = merged
    # highest relevance wins
    base["relevance_score"] = max(base.get("relevance_score") or 0.0,
                                  dup.get("relevance_score") or 0.0)
    # a known position type beats 'unknown'
    if (base.get("position_type") in (None, "unknown")
            and dup.get("position_type") not in (None, "unknown")):
        base["position_type"] = dup["position_type"]
    # fill any missing scalar fields from the duplicate
    for f in ("institution", "country", "deadline", "posted_date", "url",
              "short_description"):
        if not base.get(f) and dup.get(f):
            base[f] = dup[f]
    # the better-sourced freshness signal wins (deadline > posted > ...)
    if (_FRESHNESS_QUALITY.get(dup.get("freshness"), -1)
            > _FRESHNESS_QUALITY.get(base.get("freshness"), -1)):
        for f in ("freshness", "effective_date", "age_days"):
            base[f] = dup.get(f)
    base["is_new"] = base.get("is_new") or dup.get("is_new")


def dedupe_records(records: list[dict]) -> list[dict]:
    # pass 1: identical normalized URL = the same posting by definition
    # (metadata quality may differ, e.g. a board's search card vs the seed-
    # fetched posting page — the first/richer record absorbs the other)
    by_url: dict[str, dict] = {}
    stage: list[dict] = []
    for r in records:
        u = normalize_url(r.get("url"))
        if u and u in by_url:
            _merge_into(by_url[u], r)
            continue
        if u:
            by_url[u] = r
        stage.append(r)
    # pass 2: title+institution (the same job posted on several boards)
    index: dict[tuple, dict] = {}
    order: list[tuple] = []
    for r in stage:
        k = dedupe_key(r)
        if k in index:
            _merge_into(index[k], r)
        else:
            index[k] = r
            order.append(k)
    return [index[k] for k in order]

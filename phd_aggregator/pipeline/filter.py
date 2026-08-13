"""pipeline.filter — the filtering stage (migration Step 7, part 2).

Apply the position-type gate, the tiered relevance engine, the expiry
filter, and the region filter — in that order. Extracted verbatim from the
original monolith.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Iterable, Optional

from core.config import Config
from core.taxonomy import classify_position_type, country_allowed, \
    is_relevant, score_relevance
from core.utils import canonical_country, guess_country

log = logging.getLogger("phd_aggregator")


# Filtering: position type -> relevance -> deadline -> region
# -----------------------------------------------------------------------------
def filter_records(records: Iterable[dict], cfg: Config,
                   stats: Optional[dict] = None) -> list[dict]:
    """Filter/score a feed of records.

    NOTE: mutates input records in-place (sets position_type,
    relevance_score, matched_anchors, matched_keywords, country).

    Applies the position-type gate, the tiered relevance engine, the expiry
    filter, and the region filter — in that order. When ``stats`` is given it
    is filled with the per-stage drop counts, so a caller can tell the user
    WHY the number shrank instead of only showing the survivors.
    """
    all_records = list(records)
    kept: list[dict] = []
    today = date.today().isoformat()
    drop_type = drop_rel = drop_expired = drop_geo = 0

    for r in all_records:
        try:
            title = r.get("title") or ""
            desc = r.get("short_description") or ""
            # hand-picked seeds bypass the type + relevance GATES (they are
            # still classified, scored, deadline- and freshness-filtered)
            gate_bypass = bool(r.get("_seed")) and cfg.seed_bypass_gate

            # 1) position type (hard gate; source-provided type wins)
            ptype = r.get("position_type") or classify_position_type(title, desc)
            r["position_type"] = ptype
            if ptype not in cfg.wanted_types:
                if not (ptype == "unknown" and cfg.keep_ambiguous):
                    if gate_bypass:
                        log.info("[filter] seed kept despite type=%s (gate "
                                 "bypass): %s", ptype, title[:70])
                    else:
                        drop_type += 1
                        if cfg.debug:
                            log.debug("[filter] type=%s dropped: %s",
                                      ptype, title[:70])
                        continue
            elif ptype == "unknown" and cfg.strict_phd_only:
                # --phd-only: only verifiable PhDs, no ambiguity allowed
                if gate_bypass:
                    log.info("[filter] seed kept despite unknown type "
                             "(strict, gate bypass): %s", title[:70])
                else:
                    drop_type += 1
                    if cfg.debug:
                        log.debug("[filter] strict phd-only dropped "
                                  "(unknown type): %s", title[:70])
                    continue

            # 2) relevance (score on title+description ONLY)
            score, anchors, ctx, negs = score_relevance(title, desc, cfg)
            r["relevance_score"] = round(score, 2)
            r["matched_anchors"] = anchors
            r["matched_keywords"] = anchors + ctx
            title_anchors = ([t for t, rx in cfg._core_rx if rx.search(title)]
                             if cfg.require_title_anchor else None)
            if not is_relevant(score, anchors, cfg,
                               title_anchors=title_anchors) and not gate_bypass:
                drop_rel += 1
                if cfg.debug:
                    log.debug("[filter] relevance %.1f (anchors=%s negs=%s) "
                              "dropped: %s", score, anchors, negs, title[:70])
                continue

            # 3) expiry (keep entries with no/unparseable deadline)
            if cfg.exclude_expired:
                dl = r.get("deadline")
                if dl and dl < today:
                    drop_expired += 1
                    continue

            # 4) region — country precedence: explicit country_hint seen on the
            #    listing > free-text guess (title/desc/location/institution) >
            #    board-provided default country
            hint = r.get("country_hint")
            canon = canonical_country(hint) if hint else None
            if not canon:
                text = " ".join(filter(None, [
                    title, desc, r.get("raw_location"), r.get("institution")]))
                canon = guess_country(text) or canonical_country(r.get("country"))
            keep_geo, _flagged = country_allowed(canon, cfg)
            if not keep_geo:
                drop_geo += 1
                continue
            r["country"] = canon or "Unknown"

            kept.append(r)
        except Exception as exc:
            log.debug("filter skipped a record: %s", exc)

    log.info("[filter] raw=%d -> kept=%d (type-gate=%d relevance=%d "
             "expired=%d geo=%d)", len(all_records), len(kept),
             drop_type, drop_rel, drop_expired, drop_geo)
    if stats is not None:
        stats.update({
            "raw": len(all_records),
            "kept": len(kept),
            "dropped_position_type": drop_type,
            "dropped_relevance": drop_rel,
            "dropped_expired": drop_expired,
            "dropped_country": drop_geo,
        })
    return kept

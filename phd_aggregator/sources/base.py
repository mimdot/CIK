"""sources.base — shared registry + helpers for the crawler source layer.

Holds the ``SOURCES`` registry, the ``register_source`` decorator and the
generic ``_feed_records`` helper that several feed sources share. Migrated
verbatim from phd_aggregator.py (migration Step 5) — same names, same behavior.
"""

from __future__ import annotations

import logging
from typing import Callable

from core.config import Config
from core.http import Http
from core.records import make_record

log = logging.getLogger("phd_aggregator")


# The source registry. Every @register_source(...) (both here and across the
# sources/ submodules) populates this dict; the monolith re-imports it so
# `phd_aggregator.SOURCES` keeps working unchanged.
SOURCES: dict[str, Callable[[Config, Http], list[dict]]] = {}


def register_source(name: str):
    def deco(fn: Callable[[Config, Http], list[dict]]):
        SOURCES[name] = fn
        return fn
    return deco


def _feed_records(feed, source: str) -> list[dict]:
    """Generic, defensive RSS/Atom -> records (used by several feed sources)."""
    out: list[dict] = []
    for entry in (getattr(feed, "entries", None) or []):
        try:
            posted = (entry.get("published_parsed")
                      or entry.get("updated_parsed")
                      or entry.get("published") or entry.get("updated"))
            desc = entry.get("summary") or entry.get("description")
            out.append(make_record(
                title=entry.get("title"),
                url=entry.get("link") or entry.get("id"),
                posted_date=posted,
                short_description=desc,
                raw_location=desc,        # try to recover a country from the text
                source=source,
            ))
        except Exception as exc:
            log.debug("[%s] skipped a malformed entry: %s", source, exc)
    return out
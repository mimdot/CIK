"""sources.base — shared registry + helpers for the crawler source layer.

Holds the ``SOURCES`` registry, the ``register_source`` decorator and the
generic ``_feed_records`` helper that several feed sources share. Migrated
verbatim from phd_aggregator.py (migration Step 5) — same names, same behavior.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from core.config import Config
from core.http import Http
from core.records import make_record

log = logging.getLogger("phd_aggregator")


# Sentinel for "this board serves every discipline" (EURAXESS, jobs.ac.uk,
# Nature Careers, FindAPhD, AcademicTransfer, AcademicJobsOnline...). A source
# that names specific fields instead is a SPECIALIST and is only crawled when
# one of those fields is selected — that is what stops a chemistry search from
# hitting the AAS Job Register.
ANY_FIELD = "*"


@dataclass(frozen=True)
class SourceInfo:
    """Registry metadata for one crawler source.

    ``fields`` is the set of field-profile names this board actually serves.
    ``(ANY_FIELD,)`` means a general, multi-discipline board that every field
    may use; naming fields explicitly marks a specialist (``aas`` -> astronomy).
    """
    name: str
    fn: Callable[[Config, Http], list[dict]]
    fields: tuple[str, ...] = (ANY_FIELD,)
    label: str = ""
    note: str = ""
    # Measurably slower than the rest — excluded from a run unless the user
    # asks for it. `cost_note` is shown next to the opt-in so the time price
    # is stated up front rather than discovered.
    slow: bool = False
    cost_note: str = ""

    @property
    def is_general(self) -> bool:
        return ANY_FIELD in self.fields

    def serves(self, field_name: Optional[str]) -> bool:
        """True if this source should be crawled for ``field_name``.

        General boards serve everything. A specialist serves only the fields it
        names. ``None`` (no field selected) keeps the old behaviour: everything
        is on the table and ``sources_enabled`` alone decides.
        """
        if self.is_general or field_name is None:
            return True
        return field_name in self.fields


# The source registry. Every @register_source(...) (both here and across the
# sources/ submodules) populates this dict; the monolith re-imports it so
# `phd_aggregator.SOURCES` keeps working unchanged. SOURCE_INFO carries the
# richer metadata alongside it — same keys, same insertion order.
SOURCES: dict[str, Callable[[Config, Http], list[dict]]] = {}
SOURCE_INFO: dict[str, SourceInfo] = {}


def register_source(name: str, *, fields: Iterable[str] = (ANY_FIELD,),
                    label: str = "", note: str = "", slow: bool = False,
                    cost_note: str = ""):
    """Register a crawler source under ``name``.

    ``fields`` declares which disciplines the board serves — omit it for a
    general multi-discipline board, or pass e.g. ``fields=("astronomy",)`` for
    a specialist. See :func:`resolve_sources_for_field`.

    ``slow=True`` keeps the source OUT of a normal run; the caller must opt in.
    """
    field_tuple = tuple(dict.fromkeys(str(f).strip() for f in fields
                                      if str(f).strip())) or (ANY_FIELD,)

    def deco(fn: Callable[[Config, Http], list[dict]]):
        SOURCES[name] = fn
        SOURCE_INFO[name] = SourceInfo(name=name, fn=fn, fields=field_tuple,
                                       label=label or name, note=note,
                                       slow=slow, cost_note=cost_note)
        return fn
    return deco


def slow_sources() -> list[str]:
    """Names of the opt-in, measurably-slow sources."""
    return [n for n, info in SOURCE_INFO.items() if info.slow]


def general_sources() -> list[str]:
    """Names of the multi-discipline boards, in registration order."""
    return [n for n, info in SOURCE_INFO.items() if info.is_general]


def sources_for_field(field_name: Optional[str]) -> list[str]:
    """Names of every registered source that serves ``field_name``."""
    return [n for n, info in SOURCE_INFO.items() if info.serves(field_name)]


def specialist_sources_for_field(field_name: Optional[str]) -> list[str]:
    """Names of the FIELD-SPECIFIC (non-general) sources serving a field."""
    if field_name is None:
        return []
    return [n for n, info in SOURCE_INFO.items()
            if not info.is_general and field_name in info.fields]


def resolve_sources_for_field(field_name: Optional[str],
                              sources_enabled: dict[str, bool],
                              profile_sources: Optional[list[str]] = None,
                              known_sources: Optional[Iterable[str]] = None,
                              include_slow: bool = False,
                              ) -> dict[str, bool]:
    """Decide which sources a run for ``field_name`` should actually crawl.

    Two independent gates, deliberately kept separate:

    * **relevance** — does this board serve the selected field? That is the
      union of (a) every general multi-discipline board, (b) every specialist
      that names the field in its ``@register_source(fields=...)``, and (c)
      anything the field profile lists in its own ``sources:`` block (so a new
      field can claim a board without touching Python).
    * **permission** — ``sources_enabled`` from ``config.yaml``, the user's
      global on/off switch. It can only ever turn a source OFF.

    Effective = relevant AND enabled. With ``field_name=None`` relevance is a
    no-op and the result is exactly the old ``sources_enabled`` behaviour.

    ``known_sources`` is the set of source names to decide over; callers that
    hold their own registry reference (``fetch_sources``, tests) must pass it
    so a swapped-in registry is honoured. Defaults to everything registered.

    Logs a clear line when a field has no dedicated source of its own, so
    "why am I only seeing general boards for X?" is answerable from the log.
    """
    claimed = {str(s).strip() for s in (profile_sources or []) if str(s).strip()}
    unknown = sorted(claimed - set(SOURCE_INFO))
    if unknown:
        log.warning("field %r lists unknown source(s) in its `sources:` block: "
                    "%s — ignored (run --list-sources to see valid names)",
                    field_name, ", ".join(unknown))
        claimed -= set(unknown)

    # Decide over the caller's registry, not SOURCE_INFO: anything registered
    # straight into a SOURCES dict (tests, plugins, older third-party code) has
    # no metadata, and must be treated as a GENERAL board so it behaves exactly
    # as it did before this registry existed. Never silently drop a source.
    names = list(known_sources) if known_sources is not None else list(SOURCES)
    resolved: dict[str, bool] = {}
    skipped_slow: list[str] = []
    for name in dict.fromkeys(names):
        info = SOURCE_INFO.get(name)
        relevant = name in claimed or (info.serves(field_name) if info
                                       else True)
        if relevant and info is not None and info.slow and not include_slow:
            # Opt-in only: an exhaustive sweep must never be the thing that
            # makes a normal search feel broken.
            relevant = False
            if sources_enabled.get(name, False):
                skipped_slow.append(name)
        resolved[name] = bool(relevant and sources_enabled.get(name, False))
    if skipped_slow:
        log.info("[sources] skipped (slow, opt-in): %s — enable with "
                 "--include-slow-sources", ", ".join(sorted(skipped_slow)))

    if field_name is not None:
        dedicated = [n for n in (set(specialist_sources_for_field(field_name))
                                 | claimed) if resolved.get(n)]
        if not dedicated:
            log.info("[sources] no dedicated sources for %r yet — using the "
                     "general multi-discipline boards with %s's own keywords "
                     "(add a `sources:` block to fields/%s.yaml to change this)",
                     field_name, field_name, field_name)
        else:
            log.info("[sources] %r: %d dedicated + %d general board(s)",
                     field_name, len(dedicated),
                     sum(1 for n, on in resolved.items()
                         if on and n not in dedicated))
        skipped = [n for n, on in resolved.items()
                   if not on and sources_enabled.get(n, False)]
        if skipped:
            log.info("[sources] not relevant to %r, skipped: %s",
                     field_name, ", ".join(sorted(skipped)))
    return resolved


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
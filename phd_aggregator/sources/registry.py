"""sources.registry — the per-source, per-field URL registry (data, not code).

Every board names disciplines in its OWN vocabulary. Building a URL by pasting
our field name into a path is a guess dressed up as an address, and it fails
silently: the board answers 200 with an empty result set, or its own 404 page,
and the run reports "0 found" as if the discipline simply had no openings.

So the mapping lives in ``url_registry.yaml`` next to this module, one entry per
(source, field), each carrying whether it has actually been checked. This module
loads it and turns an entry into concrete URLs.

Resolution order for a source's targeting values, highest first:

1. the field profile's own ``source_options.<source>.<key>`` block — a profile
   can always correct the registry without a code change;
2. this registry;
3. ``[]`` — the source skips itself and says so in the log.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field as dc_field
from typing import Any, Iterator, Optional
from urllib.parse import urlencode

from core.deps import yaml

log = logging.getLogger("phd_aggregator")

_HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY_PATH = os.path.join(_HERE, "url_registry.yaml")


def _resolve_registry_path() -> str:
    """Find url_registry.yaml in-place, installed, or inside a frozen bundle.

    Mirrors core.config._find_config_path: the packaged desktop sidecar runs
    with the app-data dir as its CWD, so "next to the module" is not enough.
    """
    candidates = [REGISTRY_PATH,
                  os.path.join(os.getcwd(), "sources", "url_registry.yaml")]
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(os.path.join(exe_dir, "sources",
                                       "url_registry.yaml"))
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(os.path.join(meipass, "sources",
                                           "url_registry.yaml"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return REGISTRY_PATH

# Every field profile serves this pseudo-field: "this board is general, it takes
# whatever keywords the active profile supplies".
ANY_FIELD = "*"


@dataclass(frozen=True)
class FieldTarget:
    """What one (source, field) pair resolves to."""
    source: str
    field: str
    values: tuple[Any, ...] = ()
    adjacent: tuple[Any, ...] = ()
    status: str = "unverified"
    verified: Optional[str] = None
    note: str = ""

    @property
    def is_keyword_driven(self) -> bool:
        """True for general boards: the profile's search terms are the query."""
        return self.field == ANY_FIELD and not self.values


@dataclass(frozen=True)
class SourceSpec:
    """One board's URL grammar."""
    name: str
    label: str = ""
    transport: str = "html"            # html | feed | browser
    url_template: str = ""
    result_selector: str = ""
    param: str = ""
    facet_param: str = ""
    facet_prefix: str = ""
    static_params: tuple[tuple[str, str], ...] = ()
    note: str = ""
    fields: dict[str, FieldTarget] = dc_field(default_factory=dict)

    def target(self, field_name: Optional[str]) -> Optional[FieldTarget]:
        """The entry for ``field_name``, falling back to the general ``*``."""
        if field_name and field_name in self.fields:
            return self.fields[field_name]
        return self.fields.get(ANY_FIELD)

    def urls_for(self, field_name: Optional[str],
                 keywords: Optional[list[str]] = None) -> list[str]:
        """Concrete URLs this source would request for ``field_name``.

        This is what ``--validate-sources`` fetches, so it must be the SAME
        address the crawler builds — a validator that checks a different URL
        than the run uses is worse than no validator.
        """
        target = self.target(field_name)
        if target is None:
            return []
        values = list(target.values)

        # Facet grammar (Drupal): f[0]=prefix:v1&f[1]=prefix:v2. Adjacent
        # subjects are a SEPARATE sweep in the crawler, so they get their own
        # URL here too — a validator that checks a merged URL is not checking
        # what the run actually requests.
        if self.facet_param and values:
            def _facet_url(vals):
                params = [(self.facet_param.format(i=i),
                           f"{self.facet_prefix}{v}")
                          for i, v in enumerate(vals)]
                params.extend(self.static_params)
                return f"{self.url_template}?{urlencode(params)}"
            urls = [_facet_url(values)]
            urls.extend(_facet_url([adj]) for adj in target.adjacent)
            return urls

        # Path grammar: one URL per slug/category.
        if "{" in self.url_template and values:
            key = self.param or "value"
            return [self.url_template.format(**{key: v})
                    for v in values + list(target.adjacent)]

        # Keyword grammar: the active profile's own terms are the query.
        if self.param and keywords:
            out = []
            for kw in keywords:
                params = [(self.param, kw), *self.static_params]
                out.append(f"{self.url_template}?{urlencode(params)}")
            return out

        if self.static_params:
            return [f"{self.url_template}?{urlencode(list(self.static_params))}"]
        return [self.url_template] if self.url_template else []


_CACHE: Optional[dict[str, SourceSpec]] = None


def _coerce_target(source: str, name: str, raw: Any,
                   param: str) -> FieldTarget:
    raw = raw if isinstance(raw, dict) else {}
    values = raw.get(param)
    if values is None:
        # Some entries key their values by the source's param name, others are
        # pure keyword boards with nothing to list.
        values = raw.get("values") or []
    if not isinstance(values, list):
        values = [values]
    adjacent = raw.get("adjacent") or []
    if not isinstance(adjacent, list):
        adjacent = [adjacent]
    return FieldTarget(
        source=source, field=name,
        values=tuple(values), adjacent=tuple(adjacent),
        status=str(raw.get("status") or "unverified"),
        verified=raw.get("verified") or None,
        note=str(raw.get("note") or ""),
    )


def load_registry(path: Optional[str] = None,
                  force: bool = False) -> dict[str, SourceSpec]:
    """Parse ``url_registry.yaml`` (cached). Never raises: a broken registry
    degrades to "no targeting data", which every source already handles by
    skipping itself loudly."""
    global _CACHE
    if _CACHE is not None and not force and path is None:
        return _CACHE
    target_path = path or _resolve_registry_path()
    specs: dict[str, SourceSpec] = {}
    if yaml is None:
        log.warning("[registry] PyYAML not installed — url_registry.yaml "
                    "ignored, sources fall back to their profile options")
        if path is None:
            _CACHE = specs
        return specs
    try:
        with open(target_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        log.warning("[registry] %s not found — no per-field URL targeting",
                    target_path)
        data = {}
    except Exception as exc:
        log.error("[registry] could not parse %s (%s) — no per-field URL "
                  "targeting", target_path, exc)
        data = {}

    for name, raw in (data.get("sources") or {}).items():
        raw = raw if isinstance(raw, dict) else {}
        param = str(raw.get("param") or "")
        statics = tuple(
            (str(p[0]), str(p[1]))
            for p in (raw.get("static_params") or [])
            if isinstance(p, (list, tuple)) and len(p) == 2)
        fields = {
            fname: _coerce_target(name, fname, fraw, param)
            for fname, fraw in (raw.get("fields") or {}).items()
        }
        specs[name] = SourceSpec(
            name=name,
            label=str(raw.get("label") or name),
            transport=str(raw.get("transport") or "html"),
            url_template=str(raw.get("url_template") or ""),
            result_selector=str(raw.get("result_selector") or ""),
            param=param,
            facet_param=str(raw.get("facet_param") or ""),
            facet_prefix=str(raw.get("facet_prefix") or ""),
            static_params=statics,
            note=str(raw.get("note") or ""),
            fields=fields,
        )
    if path is None:
        _CACHE = specs
    return specs


def spec_for(source: str) -> Optional[SourceSpec]:
    return load_registry().get(source)


def values_for(cfg, source: str, option_key: str,
               field_name: Optional[str] = None) -> list:
    """Targeting values for ``source`` under the active profile.

    The profile's ``source_options.<source>.<option_key>`` always wins, so a
    user can correct a stale registry entry from their own YAML.
    """
    explicit = cfg.source_option(source, option_key)
    if isinstance(explicit, list) and explicit:
        return list(explicit)
    if field_name is None:
        field_name = (getattr(cfg, "field_profile", "") or "").strip().lower()
    spec = spec_for(source)
    if spec is None:
        return []
    target = spec.target(field_name)
    return list(target.values) if target else []


def iter_entries() -> Iterator[tuple[SourceSpec, FieldTarget]]:
    """Every (source, field) entry in the registry, for validation/reporting."""
    for spec in load_registry().values():
        for target in spec.fields.values():
            yield spec, target

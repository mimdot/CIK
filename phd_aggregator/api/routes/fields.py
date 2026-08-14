"""api.routes.fields — the field/subfield catalogue the whole UI is driven by.

One endpoint pair, three consumers:

* the FIELD selector (the most important control in the app),
* the SUBFIELD multi-select that scopes both position and supervisor search,
* the KEYWORD PICKER, which browses the curated per-subfield vocabulary so a
  user never has to depend on CV parsing or an AI service to describe their
  interests.

Everything here is derived from ``fields/*.yaml`` — data, not code — so adding
a discipline is a YAML file and nothing else.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core import position_types
from core.normalize import suggest_country, suggest_institution
from core.config import (FIELD_PROFILE, SOURCES_ENABLED, list_field_profiles,
                         load_field_profile)
from sources.base import (SOURCE_INFO, general_sources,
                          specialist_sources_for_field)

router = APIRouter(prefix="/api/fields", tags=["meta"])


def _humanize(name: str) -> str:
    """'computer_science' -> 'Computer Science'."""
    return name.replace("_", " ").title()


def _subfields(profile: dict, with_keywords: bool) -> list[dict]:
    subfields = profile.get("subfields")
    if not isinstance(subfields, dict):
        return []
    out: list[dict] = []
    for key, value in subfields.items():
        if not isinstance(value, dict):
            continue
        keywords = [str(k) for k in (value.get("keywords") or [])
                    if str(k).strip()]
        entry = {
            "id": str(key),
            "label": str(value.get("label") or _humanize(str(key))),
            "keyword_count": len(keywords),
        }
        if with_keywords:
            entry["keywords"] = keywords
        out.append(entry)
    return out


def _source_summary(name: str) -> dict:
    """Which boards this field will actually be searched on, and why.

    Only boards that are switched ON are listed — the registry also holds
    documented-but-disabled stubs (IAU, AstroBetter, regional placeholders),
    and advertising those as coverage the user is getting would be a lie.
    """
    def _on(n: str) -> bool:
        return n in SOURCE_INFO and SOURCES_ENABLED.get(n, False)

    profile = load_field_profile(name) or {}
    claimed = [str(s) for s in (profile.get("sources") or [])]
    dedicated = [n for n in dict.fromkeys(
        [*specialist_sources_for_field(name), *claimed]) if _on(n)]
    return {
        "dedicated": [{"name": n, "label": SOURCE_INFO[n].label}
                      for n in dedicated],
        "general": [{"name": n, "label": SOURCE_INFO[n].label}
                    for n in general_sources() if _on(n)],
        # Surfaced so the UI can say "no dedicated boards for X yet — searching
        # the general ones with X's own keywords" instead of leaving the user
        # to wonder why a niche field returns fewer sources.
        "has_dedicated": bool(dedicated),
    }


@router.get("")
def list_fields() -> dict:
    """Every shipped field profile, with enough detail to render the pickers.

    ``profiles`` (a bare list of names) is kept for backward compatibility with
    the existing dropdowns; ``fields`` carries the richer records.
    """
    names = sorted(list_field_profiles())
    fields = []
    for name in names:
        profile = load_field_profile(name) or {}
        description = str(profile.get("description") or "").strip()
        fields.append({
            "name": name,
            "label": _humanize(name),
            "description": description,
            "subfields": _subfields(profile, with_keywords=False),
        })
    return {"default": FIELD_PROFILE, "profiles": names, "fields": fields}


@router.get("/position-types", tags=["meta"])
def position_type_catalogue() -> dict:
    """The position types a user may search for, plus the planned ones.

    Data-driven (``position_types.yaml``), so Master's and Scholarships become
    real options by flipping one flag — the UI needs no change, it already
    renders whatever this returns and disables what is not enabled yet.
    """
    return {
        "types": [
            {
                "name": t.name,
                "label": t.label,
                "description": t.description,
                "enabled": t.enabled,
            }
            for t in position_types.TYPES if t.selectable
        ],
        "default": [t.name for t in position_types.offered_types()],
    }


@router.get("/normalize", tags=["meta"])
def normalize_names(country: str | None = None,
                    institution: str | None = None) -> dict:
    """Auto-correct a country or institution the user typed (Phase 2D).

    Resolves against the full ISO-3166 list (249 countries, every alpha-2/3
    code, plus colloquial aliases) and a curated institution table, tolerating
    misspellings. Returns the canonical form, HOW it was reached and a
    confidence, so the UI can say "did you mean Germany?" instead of silently
    rewriting what someone typed — or searching for a country that does not
    exist.
    """
    out: dict = {}
    if country is not None:
        hit = suggest_country(country)
        out["country"] = None if hit is None else {
            "input": country, "value": hit.value, "how": hit.how,
            "score": hit.score, "corrected": hit.is_correction,
        }
    if institution is not None:
        hit = suggest_institution(institution)
        out["institution"] = None if hit is None else {
            "input": institution, "value": hit.value, "how": hit.how,
            "score": hit.score, "corrected": hit.is_correction,
        }
    return out


@router.get("/{name}/departments")
def get_field_departments(name: str, country: str | None = None,
                          q: str | None = None) -> dict:
    """The department/institute list for a field — the MANUAL alternative to
    the exhaustive crawl.

    Sweeping these pages is the slowest thing the engine does (~150 pages for
    astronomy at a 2s crawl delay). Rather than forcing that on everyone, this
    hands the same curated list straight to the user: filter by country, search
    by name, open the department's own page. No crawling, instant.
    """
    profile = load_field_profile(name)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Unknown field {name!r}")

    rows = [d for d in (profile.get("departments") or [])
            if isinstance(d, dict) and d.get("url")]
    if country:
        wanted = country.strip().lower()
        rows = [d for d in rows
                if str(d.get("country", "")).strip().lower() == wanted]
    if q:
        needle = q.strip().lower()
        rows = [d for d in rows
                if needle in str(d.get("institution", "")).lower()
                or needle in str(d.get("country", "")).lower()]

    countries = sorted({str(d.get("country") or "Unknown")
                        for d in (profile.get("departments") or [])
                        if isinstance(d, dict) and d.get("url")})
    return {
        "field": name,
        "total": len(rows),
        "countries": countries,
        "departments": [{
            "country": str(d.get("country") or "Unknown"),
            "institution": str(d.get("institution") or d["url"]),
            "url": str(d["url"]),
            "field_specific": bool(d.get("field_specific")),
        } for d in rows],
    }


@router.get("/{name}")
def get_field(name: str) -> dict:
    """One field in full, including every subfield's curated keyword list.

    This is what the keyword picker browses. Keywords come straight from the
    profile, so they are the SAME vocabulary the relevance engine scores
    against — picking one cannot fail to match the way a free-text guess can.
    """
    profile = load_field_profile(name)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown field {name!r}. Available: "
                   f"{', '.join(sorted(list_field_profiles()))}")
    return {
        "name": name,
        "label": _humanize(name),
        "description": str(profile.get("description") or "").strip(),
        "subfields": _subfields(profile, with_keywords=True),
        # The whole-field vocabulary, for "add your own" type-ahead and for
        # users who would rather not drill into a subfield at all.
        "core_anchors": [str(t) for t in (profile.get("core_anchors") or [])],
        "search_terms": [str(t) for t in (profile.get("search_terms") or [])],
        "sources": _source_summary(name),
    }

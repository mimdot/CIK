"""Documented stub sources — intentionally not implemented, disabled by default
(iau, astrobetter) plus the regional stub factory (china, korea, new_zealand).
Migration Step 5, Batch C."""

from __future__ import annotations

from core.config import Config
from core.http import Http

from .base import log, register_source


@register_source(
    "iau", fields=("astronomy",),
    label="IAU (stub)")
def source_iau(cfg: Config, http: Http) -> list[dict]:
    """[STUB] IAU job listings. The IAU's job page (iau.org/science/
    publications/jobs) was RETIRED in the 2024/25 site redesign — verified
    2026-07: it 404s and the new iau.org has no jobs section or sitemap entry.
    Most ads that used to appear there are on the AAS Job Register (see the
    'aas' source). If the IAU revives a board, wire it here.
    """
    log.info("[iau] stub — IAU's job listings page was removed from iau.org; "
             "the AAS Job Register carries equivalent ads.")
    return []


@register_source(
    "astrobetter", fields=("astronomy",),
    label="AstroBetter Rumor Mill (stub)")
def source_astrobetter(cfg: Config, http: Http) -> list[dict]:
    """[STUB] AstroBetter Rumor Mill (astrobetter.com/wiki/Rumor+Mill).
    The rumor mill tracks POSTDOC & FACULTY hiring outcomes — it is not a feed
    of open PhD adverts, so with WANTED_POSITION_TYPES=['phd'] everything it
    could contribute would be filtered out. Left as an extension point: if you
    switch to postdoc hunting, parse the wiki tables here (they're plain HTML;
    institution + position per row, links out to the original ads).
    """
    log.info("[astrobetter] stub — rumor mill lists postdoc/faculty hiring, "
             "not PhD openings (enable + implement if you hunt postdocs).")
    return []


def _stub(name: str, note: str):
    """Factory for documented, disabled regional stubs with extension pointers."""
    @register_source(name)
    def _src(cfg: Config, http: Http) -> list[dict]:  # noqa: ANN001
        log.info("[%s] stub source (disabled by default). %s", name, note)
        return []
    _src.__doc__ = f"[STUB] {name}. {note}"
    return _src


_stub("china",
      "No unified English-language academic API. The top Chinese astronomy "
      "departments + CAS observatories (NAOC/PMO/SHAO, KIAA, Nanjing, ...) are "
      "now swept by the uni_departments source; this stub remains for national "
      "boards (gaoxiaojob/acabridge — Chinese-language, add Chinese anchors).")
_stub("korea",
      "No single public API. Candidates: individual university HR portals, "
      "BrainKorea/Higher-ed boards. Mostly HTML; some JS.")
_stub("new_zealand",
      "NZ universities post on their own sites; jobs.ac.uk and FindAPhD "
      "already carry some NZ PhDs (set COUNTRIES=['New Zealand'] to filter). "
      "To implement natively, scrape per-university HR pages (HTML).")

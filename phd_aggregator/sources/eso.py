"""source_eso — ESO recruitment feed (migration Step 5, Batch A)."""

from __future__ import annotations

from core.config import Config
from core.http import Http
from core.records import make_record
from core.utils import guess_country

from .base import log, register_source


@register_source(
    "eso", fields=("astronomy",),
    label="ESO recruitment",
    note="European Southern Observatory — astronomy only.")
def source_eso(cfg: Config, http: Http) -> list[dict]:
    """[FEED] ESO recruitment portal (recruitment.eso.org) — official RSS at
    /jobs.rss (verified live). Mostly staff/fellowship ads, but ESO
    studentships (PhD research stays in Garching/Chile) appear here and pass
    the PhD gate via 'studentship'. Location is Germany or Chile; guessed from
    the entry text when present.
    """
    feed = http.get_feed("https://recruitment.eso.org/jobs.rss")
    if not feed or not getattr(feed, "entries", None):
        log.warning("[eso] RSS empty/unreachable")
        return []
    out = []
    for e in feed.entries:
        try:
            text = " ".join(filter(None, [e.get("title"), e.get("summary"),
                                          e.get("subtitle"), e.get("author")]))
            country = guess_country(text)
            out.append(make_record(
                title=e.get("title"),
                institution="European Southern Observatory",
                country=country or "Germany",   # ESO HQ default
                url=e.get("link"),
                posted_date=(e.get("published_parsed") or e.get("published")),
                short_description=e.get("summary") or e.get("subtitle"),
                source="eso",
            ))
        except Exception as exc:
            log.debug("[eso] skipped entry: %s", exc)
    return out
"""core.saved_keys — stable identities for saved opportunities and supervisors.

A saved item has to outlive the row it came from. Listings are re-crawled and
deduplicated constantly, which reassigns ``opportunities.id``, so a saved item
keyed on that id points at a different position (or nothing) a week later. The
keys here are derived from the record's own identity instead, so the same
posting saved today and re-crawled tomorrow resolves to the same key.

Normalisation is deliberately conservative. It removes only what is *known* to
be noise — scheme and case, ``www.``, a trailing slash, tracking parameters —
because two different postings that normalise together is a far worse failure
than one posting that fails to.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Campaign/analytics parameters carry no identity: the same posting arrives with
# different ones depending on where the link was found.
_TRACKING = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "gclid", "fbclid", "mc_cid", "mc_eid", "ref", "referrer",
    "source", "trk", "trkCampaign", "_ga",
}

_WS = re.compile(r"\s+")


def normalize_url(url: str | None) -> str:
    """A URL reduced to the parts that identify the page.

    Returns "" when there is nothing usable, so callers can fall back rather
    than key on an empty string.
    """
    if not url:
        return ""
    raw = url.strip()
    if not raw:
        return ""
    # A bare "example.org/x" has no scheme; give it one so urlsplit finds the
    # host instead of treating the whole thing as a path.
    if "//" not in raw.split("?", 1)[0]:
        raw = "//" + raw
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""

    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""

    path = re.sub(r"/{2,}", "/", parts.path or "")
    if len(path) > 1:
        path = path.rstrip("/")

    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in _TRACKING]
    # Sorted so the same parameters in a different order are the same key.
    query = urlencode(sorted(kept))

    # Scheme and fragment dropped: http/https and #section are the same page.
    return urlunsplit(("", host, path, query, "")).lstrip("/") or host


def _slug(*parts: str | None) -> str:
    """A short, stable digest of free text, for records with no usable URL."""
    joined = "|".join(_WS.sub(" ", (p or "").strip().lower()) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


def opportunity_key(record: dict) -> str:
    """Stable key for an opportunity.

    Prefers the posting's own URL. Falls back to the upstream id the crawler
    stored (``source`` + ``source_raw``), which is what the opportunities table
    itself is made unique on — so even a URL-less source keys consistently.
    """
    url = normalize_url(record.get("url"))
    if url:
        return f"url:{url}"
    raw = (record.get("source_raw") or "").strip()
    if raw:
        return f"src:{(record.get('source') or '').strip().lower()}:{raw}"
    return "opp:" + _slug(record.get("source"), record.get("title"),
                          record.get("institution"))


def supervisor_key(record: dict) -> str:
    """Stable key for a supervisor.

    ORCID first: it is a persistent identifier for a *person*, which is exactly
    what is wanted and outlives any institutional page. Then the profile URL,
    then name + institution as a last resort.
    """
    orcid = (record.get("orcid") or "").strip()
    if orcid:
        return f"orcid:{orcid.lower()}"
    url = normalize_url(record.get("profile_url"))
    if url:
        return f"url:{url}"
    return "sup:" + _slug(record.get("name"), record.get("institution"))


def key_for(kind: str, record: dict) -> str:
    if kind == "opportunity":
        return opportunity_key(record)
    if kind == "supervisor":
        return supervisor_key(record)
    raise ValueError(f"unknown saved-item kind: {kind!r}")

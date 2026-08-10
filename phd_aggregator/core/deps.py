"""core.deps — single home for optional third-party dependency detection.

Detecting optional imports (feedparser, lxml, playwright, curl_cffi,
readability) used to be copy-pasted across core/http.py, core/utils.py and the
monolith. Keeping ONE detection site means the flags can never diverge and a new
optional dependency is added in exactly one place.

Every module reads these from here (``from core.deps import _HTML_PARSER``) —
including the monolith, which re-exports the names for back-compat.
"""

from __future__ import annotations

# feedparser — optional feed (RSS/Atom) reader.
try:
    import feedparser  # type: ignore
    _HAVE_FEEDPARSER = True
except ImportError:  # pragma: no cover - environment guard
    feedparser = None
    _HAVE_FEEDPARSER = False

# lxml — optional faster/robuster bs4 backend.
try:
    import lxml  # noqa: F401  (presence enables the faster bs4 parser)
    _HTML_PARSER = "lxml"
except ImportError:  # pragma: no cover - environment guard
    _HTML_PARSER = "html.parser"

# playwright — optional headless/headed browser for JS-rendered sources.
try:
    from playwright.sync_api import sync_playwright  # noqa: F401
    _HAVE_PLAYWRIGHT = True
except ImportError:
    _HAVE_PLAYWRIGHT = False

# curl_cffi — optional browser-TLS fallback for anti-bot 403s. Rotates through
# recent Chrome fingerprints when a plain request is blocked. Optional.
try:
    from curl_cffi import requests as curl_requests  # type: ignore
    _HAVE_CURL_CFFI = True
except ImportError:
    curl_requests = None
    _HAVE_CURL_CFFI = False

# readability-lxml — optional main-text extractor for seed URLs that carry
# neither JSON-LD nor useful meta tags. A naive extractor is used when missing.
try:
    from readability import Document as _ReadabilityDocument  # type: ignore
    _HAVE_READABILITY = True
except ImportError:
    _ReadabilityDocument = None
    _HAVE_READABILITY = False
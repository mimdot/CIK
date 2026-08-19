"""supervisors — the supervisor finder (migration Step 9).

Extracted verbatim from astra.py and split into focused modules:

  chain.py      --find-supervisors driver, source-selection chain, ORCID email
                 lookup, dashboard template
  aggregate.py  pure per-author aggregation + ranking (offline-testable)
  ads.py        NASA ADS literature queries (token required)
  openalex.py   OpenAlex works + author-direct queries (no token)
  arxiv.py      arXiv API fallback (no token)

The monolith re-imports every name from here, so ``astra.SOURCES``-
style access (e.g. ``P.aggregate_supervisors`` in test_supervisors.py) keeps
working unchanged.
"""

from __future__ import annotations

from .ads import _ads_request, ads_supervisor_docs  # noqa: F401
from .aggregate import _author_key, _paper_link, aggregate_supervisors  # noqa: F401
from .arxiv import ARXIV_API, arxiv_supervisor_docs  # noqa: F401
from .openalex import (  # noqa: F401
    _author_current_institution, _openalex_author_records,
    _openalex_author_recent, _openalex_works_pool, openalex_supervisor_authors,
    openalex_supervisor_docs,
)
from .chain import (  # noqa: F401
    AUTHOR_SEARCH_FMT, SOURCE_LABELS, _load_dotenv, _orcid_public_email,
    _SUPERVISOR_HTML_TEMPLATE, _supervisor_chain, _supervisor_focus,
    find_supervisors, write_supervisors_html,
)

__all__ = [
    "ARXIV_API", "AUTHOR_SEARCH_FMT", "SOURCE_LABELS",
    "_ads_request", "_author_current_institution", "_author_key",
    "_load_dotenv", "_openalex_author_records", "_openalex_author_recent",
    "_openalex_works_pool", "_orcid_public_email", "_paper_link",
    "_SUPERVISOR_HTML_TEMPLATE", "_supervisor_chain", "_supervisor_focus",
    "ads_supervisor_docs", "aggregate_supervisors", "arxiv_supervisor_docs",
    "find_supervisors", "openalex_supervisor_authors",
    "openalex_supervisor_docs", "write_supervisors_html",
]

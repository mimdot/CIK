"""sources — the crawler source layer (migration Step 5).

Each source is a self-contained module exposing a ``source_<name>`` function
registered with :func:`register_source`. The registry (``SOURCES``) and shared
helpers live in :mod:`sources.base`. Importing this package populates the
registry with every source; the monolith re-imports from here so
``phd_aggregator.SOURCES`` keeps working unchanged.
"""

from __future__ import annotations

# Registry + shared feed helper (migrated from the monolith, Step 5).
from .base import SOURCES, _feed_records, log, register_source  # noqa: F401

# Source submodules. Importing each one runs its @register_source decorators.
# (Batch A — feed/simple HTML; Batch B — HTML with pagination;
#  Batch C — JS/Playwright + complex, includes seed_urls.)
from . import (  # noqa: F401
    aas, academicjobsonline, academictransfer, esa, eso, euraxess,
    findaphd, jrecin, jobs_ac_uk, linkedin, nature_careers, seed_urls,
    stubs, uni_departments,
)


# Back-compat re-exports: every source function, so external importers and
# test_supervisors.py can `from phd_aggregator import source_eso` unchanged.
from .aas import source_aas  # noqa: F401
from .academicjobsonline import source_academicjobsonline  # noqa: F401
from .academictransfer import _academictransfer_ssr_fallback, source_academictransfer  # noqa: F401
from .esa import source_esa  # noqa: F401
from .eso import source_eso  # noqa: F401
from .euraxess import _euraxess_card, source_euraxess  # noqa: F401
from .findaphd import source_findaphd  # noqa: F401
from .jrecin import source_jrecin  # noqa: F401
from .jobs_ac_uk import source_jobs_ac_uk  # noqa: F401
from .linkedin import (_LINKEDIN_GIG_RE, LINKEDIN_GUEST_URL, LINKEDIN_KEYWORDS,  # noqa: F401
                       LINKEDIN_LOCATIONS, LINKEDIN_MAX_PAGES,
                       _linkedin_card, source_linkedin)
from .nature_careers import source_nature_careers  # noqa: F401
from .seed_urls import (_adapt_academicjobsonline, _read_seed_file,  # noqa: F401
                        discover_siblings, source_seed_urls)
from .stubs import _stub, source_astrobetter, source_iau  # noqa: F401
from .uni_departments import (_PHD_LINK_BLOCK_RE, _PHD_LINK_RE,  # noqa: F401
                              UNIVERSITY_DEPARTMENTS, source_uni_departments)

__all__ = [
    "source_aas", "source_academicjobsonline", "source_academictransfer",
    "source_esa", "source_eso", "source_euraxess", "source_findaphd",
    "source_jrecin", "source_jobs_ac_uk", "source_linkedin",
    "source_nature_careers", "source_seed_urls", "source_uni_departments",
    "_academictransfer_ssr_fallback", "discover_siblings",
    "_LINKEDIN_GIG_RE", "LINKEDIN_GUEST_URL", "LINKEDIN_KEYWORDS",
    "LINKEDIN_LOCATIONS", "LINKEDIN_MAX_PAGES", "UNIVERSITY_DEPARTMENTS",
    "source_astrobetter", "source_iau",
    "register_source", "SOURCES", "_feed_records",
]
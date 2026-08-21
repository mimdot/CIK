"""cli — Track C command handlers (Sprint 03).

Keeps astra.py lean: all C1-C4 logic lives here and is re-exported
through the monolith.

- C1 ``build_profile_cmd``:  LLM-extract a UserProfile from CV text and save
  it as the active profile in the DB.
- C2 ``seed_db_cmd``:        seed opportunities from the pipeline's JSON.
- C3 ``load_active_profile``: find the active profile for ``--run`` scoring.
- C4 ``show_profile_cmd``:   print the active profile from the DB.
- C5 ``sync_supervisors_cmd``: aggregate and upsert supervisor candidates
  from all field profiles into the DB for dashboard display.

The DB is SQLite (MVP). A file-backed URL only gets created/touched when the
file already exists, so a plain aggregation run never leaves a stray DB behind.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from core.llm import LLMRouter
from core.profile import extract_profile
from core.profile_schema import UserProfile
from db.init import DEFAULT_DB_URL, count_opportunities, init_db, seed_from_json
from db.repositories import ProfileRepo, SupervisorRepo
from supervisors.fit import compute_fit, passes_relevance_gate
from core import cache as core_cache

log = logging.getLogger("astra")


def _session(db_url: str) -> Session:
    """Create an initialized SQLAlchemy session for ``db_url``."""
    engine = init_db(db_url)
    return Session(engine)


def db_available(db_url: str) -> bool:
    """True if the DB URL can be opened without a side effect.

    File-backed SQLite URLs are only considered available if the file already
    exists; in-memory/other backends are always considered available (the
    caller decides when to create them). The connection is verified with a
    trivial ``SELECT 1`` so a corrupt/unopenable store is reported as
    unavailable."""
    if db_url.startswith("sqlite:///"):
        path = db_url[len("sqlite:///"):]
        if not os.path.exists(path):
            return False
    try:
        engine = init_db(db_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def load_active_profile(db_url: str = DEFAULT_DB_URL) -> Optional[UserProfile]:
    """Return the DB's active UserProfile, or None if there is none."""
    if not db_available(db_url):
        return None
    try:
        session = _session(db_url)
    except Exception as exc:
        log.debug("no usable DB at %s: %s", db_url, exc)
        return None
    with session:
        row = ProfileRepo(session).get_active()
        if row is None:
            return None
        return UserProfile(**row.to_profile())


# --- C1 ----------------------------------------------------------------------
def build_profile_cmd(raw_text: str, db_url: str = DEFAULT_DB_URL,
                      llm: Optional[LLMRouter] = None) -> int:
    """Extract a UserProfile from CV text via the LLM and store it as the
    active profile. Returns 0 on success, 1 if extraction failed."""
    llm = llm or LLMRouter()
    profile = extract_profile(raw_text, llm)
    if profile is None:
        log.error("--build-profile: could not extract a profile from the text "
                  "(install litellm and set an API key, or pass a stub LLM).")
        return 1
    session = _session(db_url)
    with session:
        repo = ProfileRepo(session)
        repo.deactivate_all()           # the new profile becomes active
        repo.create(profile.model_dump())
        session.commit()
    print("Saved active profile:")
    print(json.dumps(profile.model_dump(), indent=2, ensure_ascii=False))
    return 0


# --- C2 ----------------------------------------------------------------------
def seed_db_cmd(path: str, db_url: str = DEFAULT_DB_URL) -> int:
    """Seed opportunities from the pipeline's JSON output. Returns 0."""
    session = _session(db_url)
    with session:
        n = seed_from_json(session, path)
        total = count_opportunities(session)
    print(f"Seeded {n} record(s) from {path} "
          f"(total opportunities in DB: {total})")
    return 0


# --- C4 ----------------------------------------------------------------------
def show_profile_cmd(db_url: str = DEFAULT_DB_URL) -> int:
    """Print the active profile from the DB. Returns 0 if found, 1 if none."""
    profile = load_active_profile(db_url)
    if profile is None:
        print("No active profile in the database. Build one with:\n"
              "    python astra.py --build-profile \"<your CV text>\"")
        return 1
    print(json.dumps(profile.model_dump(), indent=2, ensure_ascii=False))
    return 0


# --- Sprint 06, C1: admin bootstrap -------------------------------------------
def make_admin_cmd(email: str, db_url: str = DEFAULT_DB_URL) -> int:
    """Promote ``email`` to the ``admin`` role (bootstraps the first admin
    used to create invite codes). Returns 0 on success, 1 if the user is
    unknown."""
    from sqlalchemy import update
    from db.models import User

    email = (email or "").strip().lower()
    if not email:
        print("Usage: python astra.py --make-admin <email>")
        return 1
    session = _session(db_url)
    with session:
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            print(f"User {email!r} not found. Register first, then promote.")
            return 1
        session.execute(
            update(User).where(User.id == user.id).values(role="admin"))
        session.commit()
        print(f"Promoted {user.email} (user id {user.id}) to admin.")
    return 0


# --- C5 ----------------------------------------------------------------------
def sync_supervisors_cmd(
    countries: list[str],
    field: Optional[str] = None,
    db_url: str = DEFAULT_DB_URL,
) -> int:
    """CLI wrapper around :func:`sync_supervisors`; returns an exit code."""
    try:
        sync_supervisors(countries, field=field, db_url=db_url)
        return 0
    except Exception as exc:
        log.error("Supervisor sync failed: %s", exc)
        return 1


#: Candidates enriched per field+country in an interactive run. Was 25.
DEFAULT_SUPERVISOR_LIMIT = 100


def sync_supervisors(
    countries: list[str],
    field: Optional[str] = None,
    db_url: str = DEFAULT_DB_URL,
    quick: bool = False,
    limit: Optional[int] = None,
    cancel=None,
    on_progress=None,
) -> tuple[int, int]:
    """
    Sweep all field profiles (or a specific one with ``field``), run the
    supervisor finder chain for each target country, and upsert ranked
    candidates into the DB for the dashboard.

    Shared by the CLI (``--sync-supervisors``) and the API job that powers the
    desktop "run online search" button. ``quick=True`` lightens the OpenAlex
    pool/enrich settings so an interactive search from the UI finishes in
    reasonable time; the CLI keeps the deeper production settings.

    ``cancel`` is any object with ``is_cancelled()`` (see :mod:`core.cancel`);
    it is polled between field/country pairs, so a cancelled search stops after
    the pair in flight rather than running to completion. Everything already
    upserted stays — a cancelled run is a shortened one, not a discarded one.

    ``on_progress`` receives the same event shape the pipeline emits, so the
    run dialog can render a supervisor search with the machinery it already has
    for the opportunities engine: one ``start`` event, then one ``source``
    event per field/country pair as it lands.

    Returns ``(upserted, total_candidates)``.
    """
    import astra as P

    P._load_dotenv()
    token = os.environ.get(P.ADS_TOKEN_ENV)

    session = _session(db_url)
    repo = SupervisorRepo(session)

    if field:
        profiles = [field] if field in P.list_field_profiles() else []
        if not profiles:
            log.error("Field profile %r not found", field)
            return 0, 0
    else:
        profiles = P.list_field_profiles()

    countries = [c.strip() for c in countries if c.strip()]
    if not countries:
        log.error("At least one country is required")
        return 0, 0

    log.info("Syncing supervisors for %d field profile(s) x %d country(ies): %s",
             len(profiles), len(countries), ", ".join(countries))

    total_upserted = 0
    total_candidates = 0
    # Candidates found but rejected by the database. Counting these is what
    # separates "the search found nobody" from "the search found people and
    # every save failed" — which looked identical from the UI (completed,
    # 0 records) while the log quietly repeated `no such column`.
    total_failed = 0
    first_failure: list[Optional[str]] = [None]

    # Interactive (UI) runs are lighter so a user gets results, not a wait —
    # but 25 candidates per field was far too tight a cap and is what produced
    # "the number of supervisor results is limited or low - just 25 for each
    # field". The interactive default is now 100, overridable per call.
    pool_pages = 2 if quick else 3
    author_enrich = (limit or DEFAULT_SUPERVISOR_LIMIT) if quick else 80
    recent_works = 10 if quick else 25

    if on_progress:
        on_progress({"event": "start", "total": len(profiles) * len(countries)})

    stopped = False
    for profile_name in profiles:
        if stopped:
            break
        prof = P.load_field_profile(profile_name) or {}
        for country in countries:
            # Cooperative cancel, checked between pairs: the pair in flight
            # finishes its current request and nothing new is started.
            if cancel is not None and cancel.is_cancelled():
                log.info("[sync] cancelled — stopping before %s / %s",
                         profile_name, country)
                stopped = True
                break
            t0 = time.time()
            # Reported to the run dialog in the finally below, so a pair shows
            # up whichever way it leaves the loop — found nobody, raised, or
            # completed normally.
            pair_status = "error"
            pair_records = 0
            try:
                cfg = P.build_config(
                    argparse.Namespace(no_config=True, debug=False, phd_only=False, field=None)
                )
                P.apply_field_profile(cfg, prof)
                cfg.field_profile = profile_name
                cfg.subfield = None
                P.compile_taxonomy(cfg)
                cfg.countries = [country]
                cfg.delay = 0.4
                if quick:
                    # AN INTERACTIVE SEARCH MUST STAY INTERRUPTIBLE.
                    #
                    # Retries live inside the session adapter, so ONE raw_get
                    # can block for timeout x (retries + 1) plus backoff — with
                    # the defaults, about 80 seconds of uninterruptible wait,
                    # and longer through a slow proxy. Cancellation is polled
                    # between requests, so a Stop click could not be noticed
                    # for well over a minute: pressing it appeared to do
                    # nothing at all. Measured here at 56s and still running.
                    #
                    # OpenAlex answers in well under a second when it answers
                    # at all, so a short budget costs nothing on a healthy
                    # network and fails fast on a sick one — which is also why
                    # the whole search gets quicker, not just more responsive.
                    # The CLI path (quick=False) keeps the patient defaults.
                    cfg.timeout = min(cfg.timeout, 8)
                    # KEEP the retries — OpenAlex answers 429 often enough that
                    # dropping them returns an EMPTY search (measured: pool=0
                    # in 0.7s, "works-pool query failed (429)"). What must go is
                    # the unbounded sleep those retries used to do: urllib3
                    # honouring Retry-After inside the adapter is what froze a
                    # search for 64s at a time with Stop doing nothing.
                    # Bounded backoff instead: ~0.5s, ~1s, so three attempts
                    # cost about two seconds and the cancel checks around them
                    # actually get a turn.
                    cfg.max_retries = max(2, min(cfg.max_retries, 3))
                    cfg.respect_retry_after = False
                    cfg.backoff = min(cfg.backoff, 0.5)
                cfg.supervisor_pool_pages = pool_pages
                cfg.supervisor_author_enrich = author_enrich
                cfg.supervisor_recent_works = recent_works

                label, keywords, focus_topics = P._supervisor_focus(cfg)
                log.info("[sync] field=%s country=%s keywords=%s topics=%s",
                         label, country, keywords, focus_topics)

                http = P.Http(cfg)
                # try/finally so the HTTP session is always closed — including
                # when an inner step raises and the outer handler below runs.
                try:
                    ranked, src = [], None
                    n_papers = 0

                    for s in P._supervisor_chain(cfg, token):
                        if on_progress:
                            on_progress({"event": "stage",
                                         "label": f"{label} / {country}: querying {s}"})
                        if s == "ads" and token:
                            docs = P.ads_supervisor_docs(cfg, http, token, keywords, country)
                            n_papers = len(docs)
                            ranked = P.aggregate_supervisors(docs, country, keywords) if docs else []
                            if ranked:
                                src = "ADS"
                                break
                        elif s == "openalex":
                            if focus_topics:
                                # cancel/on_progress go all the way in: this
                                # call is the whole runtime of a search, and
                                # the per-pair checks around this loop never
                                # fire for the desktop's single pair.
                                ranked = P.openalex_supervisor_authors(
                                    cfg, http, focus_topics, country,
                                    cfg.supervisor_field,
                                    cancel=cancel, on_progress=on_progress)
                                if ranked:
                                    src = "OpenAlex"
                                    break
                            docs = P.openalex_supervisor_docs(cfg, http, keywords, country)
                            n_papers = len(docs)
                            ranked = P.aggregate_supervisors(docs, country, keywords) if docs else []
                            if ranked:
                                src = "OpenAlex"
                                break
                        else:  # arxiv
                            docs = P.arxiv_supervisor_docs(cfg, http, keywords)
                            n_papers = len(docs)
                            ranked = P.aggregate_supervisors(docs, None, keywords) if docs else []
                            target_cty = P.canonical_country(country)
                            ranked = [r for r in ranked if r["country"] in (target_cty, "unverified")]
                            if ranked:
                                src = "arXiv"
                                break

                    if not ranked:
                        log.warning("[sync] %s / %s: no candidates from any source",
                                    label, country)
                        pair_status = "done"
                        continue

                    # Phase 4B: drop researchers whose recent work does not
                    # touch the requested topics at all. Output and seniority
                    # alone used to carry an off-field candidate into the
                    # results ("I saw non-related field results").
                    before_gate = len(ranked)
                    ranked = [r for r in ranked
                              if passes_relevance_gate(r, keywords)]
                    if before_gate != len(ranked):
                        log.info("[sync] %s / %s: dropped %d off-field "
                                 "candidate(s) with no topic overlap",
                                 label, country, before_gate - len(ranked))

                    if on_progress:
                        on_progress({
                            "event": "stage",
                            "label": f"{label} / {country}: saving {len(ranked)} candidate(s)",
                        })
                    # Map ranked candidates to Supervisor data and upsert
                    for r in ranked:
                        fit = compute_fit(
                            r, keywords, wanted_country=P.canonical_country(country),
                            senior_signal=cfg.supervisor_senior_signal)
                        topics = _topics_to_json(r.get("topics"))
                        sup_data = {
                            "source": src,
                            "name": r.get("name"),
                            "institution": r.get("institution"),
                            # Supervisor has no dedicated institution field; the
                            # department column doubles as the institution.
                            "department": r.get("institution"),
                            "country": r.get("country"),
                            "profile_url": r.get("author_search") or r.get("orcid_link"),
                            "email": r.get("public_email"),
                            "topics": topics,
                            # methods column reuses topics until a candidate
                            # provides a separate methods breakdown.
                            "methods": topics,
                            "recent_papers": _papers_to_json(r.get("representative_papers")),
                            # Explainable 0-100 fit (Phase 4C) — replaces the
                            # unbounded raw ranking score, which meant nothing
                            # on its own and was not comparable across fields.
                            "fit_score": fit["fit_score"],
                            "fit_explanation": fit["fit_explanation"],
                            "confidence": round(fit["fit_score"] / 100.0, 3),
                        }
                        try:
                            repo.upsert(sup_data)
                            total_upserted += 1
                        except Exception as e:
                            total_failed += 1
                            if first_failure[0] is None:
                                first_failure[0] = f"{type(e).__name__}: {e}"
                            log.warning("Failed to upsert %s: %s",
                                        sup_data.get("name"), e)

                    total_candidates += len(ranked)
                    pair_records = len(ranked)
                    pair_status = "done"
                    log.info("[sync] %s / %s: %d candidates (src=%s, %.1fs)",
                             label, country, len(ranked), src, time.time() - t0)
                finally:
                    http.close()

            except Exception as exc:
                log.error("Sync failed for %s / %s: %s", profile_name, country, exc)
                continue
            finally:
                if on_progress:
                    on_progress({
                        "event": "source",
                        "source": f"{profile_name} · {country}",
                        "status": pair_status,
                        "records": pair_records,
                        "duration": round(time.time() - t0, 1),
                    })

    session.commit()
    session.close()
    core_cache.invalidate_supervisors()
    if total_failed:
        # Loud, and specific about the FIRST cause: "0 results" after finding
        # real candidates is a storage failure, not an empty search, and the
        # user cannot tell those apart from the outside.
        raise RuntimeError(
            f"found {total_candidates} supervisor candidate(s) but could not "
            f"save {total_failed} of them — first failure: {first_failure[0]}")
    log.info("Supervisor sync complete: %d upserted from %d total candidates",
             total_upserted, total_candidates)
    return total_upserted, total_candidates


def _topics_to_json(topics: Optional[str]) -> Optional[str]:
    """Convert semicolon-separated topics string to JSON array."""
    if not topics:
        return None
    return json.dumps([t.strip() for t in topics.split(";") if t.strip()])


def _papers_to_json(papers: Optional[str]) -> Optional[str]:
    """Convert pipe-separated representative papers to JSON array."""
    if not papers:
        return None
    return json.dumps([p.strip() for p in papers.split("|") if p.strip()])

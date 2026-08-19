"""api — FastAPI REST layer over the aggregator's core modules (Sprint 04,
Track A). Exposes profiles, opportunities, matches, supervisors, bookmarks,
pipeline control and auth as a RESTful API. The CLI and the monolith keep
working unchanged; this package is a thin, dependency-injected view over
``db``, ``core``, ``matching`` and ``pipeline``.
"""

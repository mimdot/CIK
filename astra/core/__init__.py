"""core — extracted subsystems of astra.py.

Module refactor per MIGRATION_PLAN.md (Steps 1-4 done):
  core.config      — CONFIG constants, Config object, config.yaml + fields/*.yaml
                     plumbing, build_config()           (Step 1)
  core.deps        — single optional-dependency detection site (feedparser,
                     lxml, playwright, curl_cffi, readability)
  core.utils       — text / date / country / URL normalization helpers
                                                         (Step 2)
  core.records     — make_record() + OUTPUT_FIELDS       (Step 2)
  core.taxonomy    — relevance scoring, position-type classifier, geo gate
                     (compile_taxonomy re-homed here)    (Step 3)
  core.http        — Http, RobotsCache, proxy detection, anti-bot chain
                                                         (Step 4)

The monolith re-imports every name from here so ``astra.py`` and its
importers (e.g. test_supervisors.py) keep working unchanged.
"""

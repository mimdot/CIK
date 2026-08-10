#!/usr/bin/env python3
"""Pytest bootstrap: make the aggregator package importable.

Allows the tests to be run from anywhere (``pytest`` from the repo root, the
phd_aggregator/ dir, or an editor) by putting the package directory on
``sys.path`` — so future test files don't each need the manual
``sys.path.insert`` dance. Also flags the test environment so the API skips
starting background threads (e.g. the weekly-digest fallback scheduler).
"""
import os
import sys

os.environ.setdefault("CIK_TESTING", "1")

_PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PACKAGE_DIR not in sys.path:
    sys.path.insert(0, _PACKAGE_DIR)

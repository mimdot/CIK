#!/usr/bin/env bash
# Fast self-test gate for CI (Sprint 07, Track C1): offline self-test + backend
# tests + dashboard tests. No network. Exits non-zero on any failure.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1. Offline CLI self-test =="
(cd astra && python3 astra.py --self-test)

echo "== 2. Backend unit/integration tests =="
(cd astra && python3 -m pytest tests/ -q)

echo "== 3. Dashboard unit tests =="
(cd dashboard && npm test -- --runInBand)

echo "SELF-TEST PASSED"

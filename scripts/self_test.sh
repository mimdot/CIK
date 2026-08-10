#!/usr/bin/env bash
# Self-test gate used by CI and deploy hooks (Sprint 07, Track C1).
# Exits non-zero on any failure.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1. Offline CLI self-test =="
(cd phd_aggregator && python3 phd_aggregator.py --self-test)

echo "== 2. Backend unit/integration tests =="
(cd phd_aggregator && python3 -m pytest tests/ -q)

echo "== 3. Dashboard unit tests =="
(cd dashboard && npm test -- --runInBand)

echo "== 4. Live source sweep (best-effort, warn-only) =="
(cd phd_aggregator && python3 test_supervisors.py --whole-only) || \
  echo "WARN: live source sweep failed (network/anti-bot) — not fatal"

echo "SELF-TEST PASSED"

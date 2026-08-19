#!/usr/bin/env bash
# Deploy-time smoke test (Sprint 07, Track C2). Run AFTER `docker compose up`.
# Verifies the stack is actually serving and that the core user journey works:
# register -> login -> build profile -> list matches -> cleanup.
#
# Set ASTRA_SMOKE_TEST=1 to have the throwaway account removed at the end, and
# API_URL / DASHBOARD_URL to point at the deployed stack (defaults localhost).
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
DASHBOARD_URL="${DASHBOARD_URL:-http://localhost:3000}"
EMAIL="smoke-$(date +%s)@example.com"
PASSWORD="SmokeTest123!"

echo "== liveness =="
curl -fsS "$API_URL/health"
echo

echo "== readiness (DB reachable) =="
curl -fsS "$API_URL/ready"
echo

echo "== dashboard =="
code=$(curl -fsS -o /dev/null -w '%{http_code}' "$DASHBOARD_URL")
echo "dashboard HTTP $code"
[ "$code" = "200" ] || { echo "FAIL: dashboard not 200"; exit 1; }

echo "== register =="
register=$(curl -fsS -X POST "$API_URL/api/auth/register" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
echo "$register"

echo "== login =="
login=$(curl -fsS -X POST "$API_URL/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
token=$(echo "$login" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
[ -n "$token" ] || { echo "FAIL: no token"; exit 1; }
AUTH="Authorization: Bearer $token"

echo "== build profile =="
profile=$(curl -fsS -X POST "$API_URL/api/profile/build" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"raw_text":"PhD candidate in astronomy studying the interstellar medium, experienced with radio interferometry, python and data analysis. Seeking postdoc positions in Germany."}')
echo "$profile" | head -c 200; echo

echo "== list matches =="
curl -fsS "$API_URL/api/matches?limit=5" -H "$AUTH" >/dev/null
echo "matches endpoint OK"

echo "== cleanup =="
# There is no /api/admin/smoke-cleanup endpoint (Sprint 10 spec only) — the
# throwaway account is left in place and the email printed so an operator can
# remove it manually if desired.
echo "left account $EMAIL in place (no automated cleanup endpoint; remove manually if desired)"

echo "SMOKE TEST PASSED"

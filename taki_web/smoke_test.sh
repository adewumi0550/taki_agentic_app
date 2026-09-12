#!/usr/bin/env bash
# Smoke test for taki-web: health, one Hausa chat through the whole chain
# (web -> MCP -> model), and the negative test (no auth -> 403).
set -uo pipefail
cd "$(dirname "$0")/.."; if [ -f .env ]; then set -a; . ./.env; set +a; fi
URL="${1:-${TAKI_WEB_URL:-}}"; [ -n "$URL" ] || { echo "usage: smoke_test.sh URL  (or set TAKI_WEB_URL)"; exit 1; }
URL="${URL%/}"
case "$URL" in http://127.*|http://localhost*) AUTH=();; *) AUTH=(-H "Authorization: Bearer $(gcloud auth print-identity-token)");; esac

echo "== GET $URL/api/health"; curl -sS "${AUTH[@]}" "$URL/api/health"; echo; echo
echo "== POST $URL/api/chat  'Sannu, yaya kake?'"
t0=$(date +%s); curl -sS "${AUTH[@]}" -X POST "$URL/api/chat" -H 'Content-Type: application/json' \
  -d '{"question":"Sannu, yaya kake?","farmer_id":"smoke"}' -o /tmp/taki_web_reply.json -w 'HTTP %{http_code}\n'
echo "  took $(( $(date +%s) - t0 ))s"; cat /tmp/taki_web_reply.json; echo; echo
if [ ${#AUTH[@]} -eq 0 ]; then echo "negative test skipped on localhost"; exit 0; fi
echo "== NEGATIVE: no auth header"
code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$URL/api/chat" -H 'Content-Type: application/json' -d '{"question":"x"}')
echo "  HTTP $code"
if [ "${TAKI_WEB_PUBLIC:-0}" = "1" ]; then
  # Farmer UI is deliberately public: assert it is REACHABLE without a login.
  if [ "$code" = "200" ]; then echo "  PUBLIC (TAKI_WEB_PUBLIC=1) — reachable without auth, as intended.";
  else echo "  FAIL — TAKI_WEB_PUBLIC=1 but no-auth call got HTTP $code (expected 200)." >&2; exit 1; fi
elif [ "$code" = "403" ] || [ "$code" = "401" ]; then echo "  PASS — web UI is private.";
else echo "  FAIL — web UI answered without auth but TAKI_WEB_PUBLIC is not set. It may be PUBLIC by accident." >&2; exit 1; fi

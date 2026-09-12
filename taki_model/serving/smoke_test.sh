#!/usr/bin/env bash
# Smoke test for the private TAKI Cloud Run service.
#
# THIS COSTS MONEY: the first request wakes a GPU instance from zero.
#
# Three things are proved here:
#   1. an authenticated chat completion works, and the reply is printed
#   2. cold-start latency and warm latency, timed separately
#   3. THE NEGATIVE TEST — the identical request with no Authorization header
#      must be rejected. An open GPU endpoint is an open bill, so a missing
#      403/401 fails this script.
set -uo pipefail

PKG_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$PKG_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [ -f .env ]; then set -a; . ./.env; set +a; fi

PY="${PY:-python3}"
CFG="$PKG_DIR/config/models.yaml"
TAKI_MODEL=$("$PY" -c "import yaml;print(yaml.safe_load(open('$CFG'))['taki_model']['name'])" 2>/dev/null || true)
if [ -z "$TAKI_MODEL" ]; then
  echo "ERROR: could not read taki_model.name from $CFG." >&2
  echo "       \$PY is '$PY' — it needs pyyaml. Run via 'make smoke', which uses the venv." >&2
  exit 1
fi

# --- resolve the service URL ----------------------------------------------
# Prefer TAKI_BASE_URL from .env; otherwise ask Cloud Run directly so the
# script still works immediately after a first deploy.
if [ -n "${TAKI_BASE_URL:-}" ]; then
  BASE_URL="${TAKI_BASE_URL%/}"
  BASE_URL="${BASE_URL%/v1}"
else
  : "${GCP_PROJECT_ID:?set GCP_PROJECT_ID in .env}"
  : "${GCP_REGION:?set GCP_REGION in .env}"
  : "${CLOUD_RUN_SERVICE:?set CLOUD_RUN_SERVICE in .env}"
  BASE_URL=$(gcloud run services describe "$CLOUD_RUN_SERVICE" \
    --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
    --format="value(status.url)" 2>/dev/null)
fi

if [ -z "$BASE_URL" ]; then
  echo "ERROR: could not resolve the service URL. Run 'make deploy' first, or" >&2
  echo "       set TAKI_BASE_URL in .env." >&2
  exit 1
fi

ENDPOINT="${BASE_URL}/v1/chat/completions"

# A real Hausa farmer question: "Sannu. There are small insects on my millet
# leaves and the leaves are curling. What should I do?"
PROMPT='Sannu. Akwai kananan kwari a ganyen geron gonata kuma ganyen na nannade. Me zan yi?'

REQ=$("$PY" - "$TAKI_MODEL" "$PROMPT" <<'PYEOF'
import json, sys
print(json.dumps({
    "model": sys.argv[1],
    "messages": [{"role": "user", "content": sys.argv[2]}],
    "temperature": 0.3,
}))
PYEOF
)

echo "=========================================================================="
echo " TAKI smoke test"
echo "=========================================================================="
echo " endpoint : $ENDPOINT"
echo " model    : $TAKI_MODEL   (from config/models.yaml)"
echo "=========================================================================="

# --- auth ------------------------------------------------------------------
echo ""
echo "==> minting identity token"
TOKEN=$(gcloud auth print-identity-token 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: could not mint an identity token. Run: gcloud auth login" >&2
  exit 1
fi
echo "    ok (identity token acquired)"

call() {
  # $1 = output body file. Echoes the wall-clock seconds for the request.
  local body_file="$1"
  local t0 t1
  t0=$("$PY" -c 'import time;print(time.time())')
  curl -sS -X POST "$ENDPOINT" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$REQ" \
    -o "$body_file" -w '%{http_code}' > "${body_file}.code" 2>"${body_file}.err"
  t1=$("$PY" -c 'import time;print(time.time())')
  "$PY" -c "print(f'{${t1} - ${t0}:.2f}')"
}

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

# --- 1. cold call ----------------------------------------------------------
echo ""
echo "==> call 1 (cold — this may scale an instance up from zero)"
COLD_S=$(call "$TMP/cold")
COLD_CODE=$(cat "$TMP/cold.code" 2>/dev/null || echo "000")

if [ "$COLD_CODE" != "200" ]; then
  echo "ERROR: authenticated call failed with HTTP $COLD_CODE" >&2
  head -c 2000 "$TMP/cold" >&2; echo >&2
  cat "$TMP/cold.err" >&2 2>/dev/null || true
  exit 1
fi

REPLY=$("$PY" -c "
import json,sys
d=json.load(open('$TMP/cold'))
print(d['choices'][0]['message']['content'].strip())
")
USAGE=$("$PY" -c "
import json
u=json.load(open('$TMP/cold')).get('usage') or {}
print(f\"prompt={u.get('prompt_tokens')} completion={u.get('completion_tokens')}\")
")

echo ""
echo "--- TAKI replied ---------------------------------------------------------"
echo "$REPLY"
echo "--------------------------------------------------------------------------"
echo "tokens: $USAGE"

# --- 2. warm call ----------------------------------------------------------
echo ""
echo "==> call 2 (warm — instance already up)"
WARM_S=$(call "$TMP/warm")
WARM_CODE=$(cat "$TMP/warm.code" 2>/dev/null || echo "000")
if [ "$WARM_CODE" != "200" ]; then
  echo "ERROR: warm call failed with HTTP $WARM_CODE" >&2
  exit 1
fi

# --- 3. NEGATIVE TEST — this is the one that matters -----------------------
echo ""
echo "==> call 3 (NEGATIVE: identical request, no Authorization header)"
NOAUTH_CODE=$(curl -sS -X POST "$ENDPOINT" \
  -H "Content-Type: application/json" \
  -d "$REQ" \
  -o "$TMP/noauth" -w '%{http_code}')

echo ""
echo "=========================================================================="
echo " RESULTS"
echo "=========================================================================="
printf " cold call        : %8ss   (HTTP %s)\n" "$COLD_S" "$COLD_CODE"
printf " warm call        : %8ss   (HTTP %s)\n" "$WARM_S" "$WARM_CODE"
printf " cold-start cost  : %8ss\n" "$("$PY" -c "print(f'{${COLD_S} - ${WARM_S}:.2f}')")"
printf " unauthenticated  : HTTP %s\n" "$NOAUTH_CODE"
echo "=========================================================================="

# Cloud Run rejects unauthenticated requests to a private service with 403.
# 401 is accepted too — both mean "refused", which is the property under test.
# Anything else, especially 200, means the endpoint is open to the internet.
if [ "${TAKI_MODEL_PUBLIC:-0}" = "1" ]; then
  # Operator has deliberately made this service public. The negative test then
  # asserts the OPPOSITE: an unauthenticated call must SUCCEED (the service is
  # reachable), and we shout about the missing lock so it is never accidental.
  if [ "$NOAUTH_CODE" = "200" ]; then
    echo " PUBLIC (TAKI_MODEL_PUBLIC=1) — unauthenticated request returned 200."
    echo " NOTE: this GPU endpoint is open to the internet. Cost ceiling is the"
    echo "       service max-instances only. Set TAKI_MODEL_PUBLIC=0 and re-run"
    echo "       deploy.sh to re-lock it."
  else
    echo " FAIL — TAKI_MODEL_PUBLIC=1 but unauthenticated call got HTTP $NOAUTH_CODE (expected 200)." >&2
    exit 1
  fi
elif [ "$NOAUTH_CODE" = "403" ]; then
  echo " PASS — unauthenticated request rejected with 403. Endpoint is private."
elif [ "$NOAUTH_CODE" = "401" ]; then
  echo " PASS — unauthenticated request rejected with 401. Endpoint is private."
else
  echo "" >&2
  echo " FAIL — expected 403, got HTTP $NOAUTH_CODE." >&2
  echo "" >&2
  echo " THE SERVICE MAY BE PUBLIC. A public GPU endpoint is an open bill and" >&2
  echo " anyone can run inference on your card. Fix it now:" >&2
  echo "" >&2
  echo "   gcloud run services remove-iam-policy-binding ${CLOUD_RUN_SERVICE:-taki} \\" >&2
  echo "     --region=${GCP_REGION:-us-central1} --member=allUsers --role=roles/run.invoker" >&2
  echo "" >&2
  head -c 500 "$TMP/noauth" >&2; echo >&2
  exit 1
fi
echo "=========================================================================="

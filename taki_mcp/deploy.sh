#!/usr/bin/env bash
# Deploy the TAKI MCP server as a PRIVATE, CPU-only Cloud Run service.
#
# Cheap: no GPU, scales to zero. What it needs:
#   * TAKI_BASE_URL          the model service URL (from .env, set by `make deploy`)
#   * model ID               read from taki_model/config/models.yaml, never a literal
#   * roles/run.invoker      on the model service, for this service's account
#   * the conversation store: Secret Manager secret $DB_DSN_SECRET holding a
#     Postgres DSN, plus roles/cloudsql.client and --add-cloudsql-instances.
#     If the secret does not exist yet the service still deploys with the
#     store DISABLED and prints exactly how to create it. Re-run to attach.
#
# Safe to re-run. Prints the service URL as its LAST line.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"
cd "$REPO_ROOT"
if [ -f .env ]; then set -a; . ./.env; set +a; fi

require() { [ -n "${!1:-}" ] || { echo "ERROR: $1 is not set (see .env.example)" >&2; exit 1; }; }
require GCP_PROJECT_ID; require GCP_REGION; require TAKI_BASE_URL

MCP_SERVICE="${MCP_SERVICE:-taki-mcp}"
DB_INSTANCE="${DB_INSTANCE:-}"                     # PROJECT:REGION:INSTANCE
DB_DSN_SECRET="${DB_DSN_SECRET:-taki-agent-dsn}"
PY="${PY:-python3}"

MODEL_ID=$("$PY" -c "import yaml;print(yaml.safe_load(open('taki_model/config/models.yaml'))['taki_model']['name'])" 2>/dev/null || true)
[ -n "$MODEL_ID" ] || { echo "ERROR: could not read model ID from taki_model/config/models.yaml (\$PY=$PY needs pyyaml; use make mcp-deploy)" >&2; exit 1; }

PROJECT_NUMBER=$(gcloud projects describe "$GCP_PROJECT_ID" --format="value(projectNumber)")
SA="${MCP_SERVICE_ACCOUNT:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"
MODEL_SERVICE="${CLOUD_RUN_SERVICE:-taki}"
MODEL_ORIGIN="${TAKI_BASE_URL%/v1}"

echo "=========================================================================="
echo " TAKI MCP deploy (CPU only, private, scales to zero)"
echo "=========================================================================="
echo " account   : $(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -1)"
echo " project   : $GCP_PROJECT_ID   region: $GCP_REGION"
echo " service   : $MCP_SERVICE   runs as: $SA"
echo " model     : $MODEL_ID @ $MODEL_ORIGIN   (id from models.yaml)"
echo " db        : ${DB_INSTANCE:-<none>}   secret: $DB_DSN_SECRET"
echo "=========================================================================="

# --- IAM: this service must be allowed to call the private model ----------
echo "==> granting roles/run.invoker on '$MODEL_SERVICE' to $SA (idempotent)"
gcloud run services add-iam-policy-binding "$MODEL_SERVICE" \
  --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --member="serviceAccount:$SA" --role="roles/run.invoker" --quiet >/dev/null

# --- conversation store wiring --------------------------------------------
DB_FLAGS=()
STORE_STATE="DISABLED"
if [ -n "$DB_INSTANCE" ]; then
  if gcloud secrets describe "$DB_DSN_SECRET" --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
    echo "==> secret '$DB_DSN_SECRET' found; attaching Cloud SQL instance $DB_INSTANCE"
    gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
      --member="serviceAccount:$SA" --role="roles/cloudsql.client" --quiet >/dev/null
    gcloud secrets add-iam-policy-binding "$DB_DSN_SECRET" --project="$GCP_PROJECT_ID" \
      --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" --quiet >/dev/null
    DB_FLAGS=(--add-cloudsql-instances="$DB_INSTANCE" --set-secrets="TAKI_DB_DSN=${DB_DSN_SECRET}:latest")
    STORE_STATE="ENABLED"
  else
    cat <<MSG
==> secret '$DB_DSN_SECRET' does not exist. Deploying with the conversation
    store DISABLED. To enable it, create the secret yourself (it contains the
    DB password, so this script will not ask for it), then re-run:

      printf '%s' 'postgresql://USER:PASSWORD@/agent_db?host=/cloudsql/${DB_INSTANCE}' \\
        | gcloud secrets create ${DB_DSN_SECRET} --project=${GCP_PROJECT_ID} --data-file=-

      make mcp-deploy
MSG
  fi
else
  echo "==> DB_INSTANCE not set; conversation store DISABLED"
fi

# --- build + deploy --------------------------------------------------------
IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${AR_REPO:-taki}/${MCP_SERVICE}:latest"
echo "==> building $IMAGE"
gcloud builds submit "$HERE" --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --tag="$IMAGE" --quiet

echo "==> deploying $MCP_SERVICE"
gcloud run deploy "$MCP_SERVICE" \
  --image="$IMAGE" \
  --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --service-account="$SA" \
  --no-allow-unauthenticated \
  --invoker-iam-check \
  --port=8080 --cpu=1 --memory=512Mi \
  --min-instances=0 --max-instances=3 --concurrency=20 --timeout=600 \
  --set-env-vars="TAKI_BASE_URL=${TAKI_BASE_URL},TAKI_MODEL_ID=${MODEL_ID},TAKI_ENV=cloudrun" \
  ${DB_FLAGS[@]+"${DB_FLAGS[@]}"} \
  --quiet

URL=$(gcloud run services describe "$MCP_SERVICE" --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --format="value(status.url)")
echo ""
echo "==> deployed private. conversation store: $STORE_STATE"
echo "==> put this in .env:   TAKI_MCP_URL=${URL}"
echo "==> then:               make mcp-smoke"
echo ""
echo "$URL"

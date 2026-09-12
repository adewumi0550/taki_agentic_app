#!/usr/bin/env bash
# Deploy TAKI to a PRIVATE Cloud Run GPU service.
#
# THIS COSTS MONEY. It provisions a GPU-backed Cloud Run service. The service
# scales to zero when idle (confirmed supported — see MODELS.md section 3), so
# you pay per request rather than per hour, but a build and a deploy are not
# free and every smoke test wakes a GPU.
#
# Properties this script guarantees:
#   * safe to re-run — creates what is missing, updates what exists
#   * always --no-allow-unauthenticated
#   * region, model ID, service name and GPU shape all come from env or from
#     config/models.yaml — no literals
#   * prints the service URL as its LAST line
#   * fails with a readable message if GPU quota is missing
set -euo pipefail

PKG_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$PKG_DIR/.." && pwd)"
cd "$REPO_ROOT"

# --- load .env -------------------------------------------------------------
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi

require() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "ERROR: $name is not set. Copy .env.example to .env and fill it in." >&2
    exit 1
  fi
}

require GCP_PROJECT_ID
require GCP_REGION
require CLOUD_RUN_SERVICE

AR_REPO="${AR_REPO:-taki}"
GPU_TYPE="${GPU_TYPE:-nvidia-l4}"
CPU="${CPU:-8}"
MEMORY="${MEMORY:-32Gi}"
MAX_INSTANCES="${MAX_INSTANCES:-1}"
CONCURRENCY="${CONCURRENCY:-4}"

# --- model IDs come from config, never from a literal ----------------------
PY="${PY:-python3}"
CFG="$PKG_DIR/config/models.yaml"
BASE_MODEL=$("$PY" -c "import yaml;print(yaml.safe_load(open('$CFG'))['taki_model']['base'])" 2>/dev/null || true)
TAKI_MODEL=$("$PY" -c "import yaml;print(yaml.safe_load(open('$CFG'))['taki_model']['name'])" 2>/dev/null || true)
if [ -z "$BASE_MODEL" ] || [ -z "$TAKI_MODEL" ]; then
  echo "ERROR: could not read model IDs from $CFG." >&2
  echo "       \$PY is '$PY' — it needs pyyaml. Run via 'make deploy', which uses the venv." >&2
  exit 1
fi

ACTIVE_ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | head -1)

echo "=========================================================================="
echo " TAKI deploy — this provisions a BILLABLE Cloud Run GPU service"
echo "=========================================================================="
echo " account      : ${ACTIVE_ACCOUNT:-<none — run gcloud auth login>}"
echo " project      : $GCP_PROJECT_ID"
echo " region       : $GCP_REGION"
echo " service      : $CLOUD_RUN_SERVICE"
echo " base model   : $BASE_MODEL      (from config/models.yaml)"
echo " taki model   : $TAKI_MODEL      (from config/models.yaml)"
echo " gpu          : 1 x $GPU_TYPE, no zonal redundancy"
echo " shape        : ${CPU} vCPU / ${MEMORY}"
echo " max instances: $MAX_INSTANCES   (hard ceiling on concurrent GPU billing)"
echo " access       : --no-allow-unauthenticated (private)"
echo "=========================================================================="

if [ -z "$ACTIVE_ACCOUNT" ]; then
  echo "ERROR: no active gcloud credential. Run: gcloud auth login" >&2
  exit 1
fi

# --- region sanity check ---------------------------------------------------
# Verified 2026-09-05, see MODELS.md section 3. A wrong region fails late and
# confusingly, so catch it here.
case "$GPU_TYPE" in
  nvidia-l4)
    VALID_REGIONS="asia-southeast1 asia-south1 europe-west1 europe-west4 us-central1 us-east4" ;;
  nvidia-rtx-pro-6000)
    VALID_REGIONS="asia-southeast1 asia-south2 europe-west4 us-central1" ;;
  *)
    echo "ERROR: unknown GPU_TYPE '$GPU_TYPE'. Expected nvidia-l4 or nvidia-rtx-pro-6000." >&2
    exit 1 ;;
esac
if ! echo " $VALID_REGIONS " | grep -q " $GCP_REGION "; then
  echo "ERROR: $GPU_TYPE is not available in region '$GCP_REGION'." >&2
  echo "       Supported regions (checked 2026-09-05): $VALID_REGIONS" >&2
  echo "       Set GCP_REGION in .env to one of those." >&2
  exit 1
fi

# --- idempotent: Artifact Registry repo ------------------------------------
IMAGE_HOST="${GCP_REGION}-docker.pkg.dev"
IMAGE="${IMAGE_HOST}/${GCP_PROJECT_ID}/${AR_REPO}/${CLOUD_RUN_SERVICE}:latest"

if gcloud artifacts repositories describe "$AR_REPO" \
      --location="$GCP_REGION" --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
  echo "==> artifact registry repo '$AR_REPO' already exists"
else
  echo "==> creating artifact registry repo '$AR_REPO'"
  gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker \
    --location="$GCP_REGION" \
    --project="$GCP_PROJECT_ID" \
    --description="TAKI serving images"
fi

# --- render the Modelfile, then build --------------------------------------
echo "==> rendering Modelfile (same renderer the local build uses)"
"$PY" "$PKG_DIR/render_modelfile.py" "$PKG_DIR/serving/Modelfile.rendered"

# Model IDs go to the build as a file, not as --build-arg: `gcloud builds
# submit --tag` has no way to pass build args, so ARGs would arrive empty.
cat > "$PKG_DIR/serving/build.env" <<ENVEOF
BASE_MODEL=$BASE_MODEL
TAKI_MODEL=$TAKI_MODEL
ENVEOF
echo "    build.env: BASE_MODEL=$BASE_MODEL TAKI_MODEL=$TAKI_MODEL"

echo "==> building image with Cloud Build: $IMAGE"
echo "    (the base weights are pulled on Google's network, not yours)"
gcloud builds submit "$PKG_DIR/serving" \
  --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" \
  --tag="$IMAGE" \
  --timeout=3600s

# --- deploy ----------------------------------------------------------------
# Output is captured so a quota rejection can be turned into a readable
# message instead of a wall of gcloud stderr.
echo "==> deploying $CLOUD_RUN_SERVICE"
DEPLOY_LOG=$(mktemp)
trap 'rm -f "$DEPLOY_LOG"' EXIT

set +e
gcloud run deploy "$CLOUD_RUN_SERVICE" \
  --image="$IMAGE" \
  --project="$GCP_PROJECT_ID" \
  --region="$GCP_REGION" \
  --no-allow-unauthenticated \
  --invoker-iam-check \
  --port=8080 \
  --cpu="$CPU" \
  --memory="$MEMORY" \
  --gpu=1 \
  --gpu-type="$GPU_TYPE" \
  --no-gpu-zonal-redundancy \
  --max-instances="$MAX_INSTANCES" \
  --concurrency="$CONCURRENCY" \
  --timeout=600 \
  --set-env-vars="OLLAMA_HOST=0.0.0.0:8080,OLLAMA_KEEP_ALIVE=-1,OLLAMA_NUM_PARALLEL=${CONCURRENCY},TAKI_MODEL=${TAKI_MODEL}" \
  2>&1 | tee "$DEPLOY_LOG"
DEPLOY_RC=${PIPESTATUS[0]}
set -e

if [ "$DEPLOY_RC" -ne 0 ]; then
  echo ""
  echo "--------------------------------------------------------------------------" >&2
  if grep -qiE 'quota|nvidia_l4_gpu_allocation|nvidia_rtx_pro_6000|GPU_ALLOCATION|exceeded' "$DEPLOY_LOG"; then
    cat >&2 <<MSG
DEPLOY FAILED: GPU QUOTA.

This project has no available Cloud Run GPU quota for:
    $GPU_TYPE  in  $GCP_REGION  (no zonal redundancy)

New projects normally get a small default allocation (3 L4 GPUs, or 3000
milliGPU of RTX PRO 6000), but that allocation was NOT readable for this
project before deploying, so this may simply be the first time it is being
exercised. Request an increase here:

    https://console.cloud.google.com/iam-admin/quotas?project=${GCP_PROJECT_ID}&service=run.googleapis.com

Filter for the metric:
    run.googleapis.com/nvidia_l4_gpu_allocation_no_zonal_redundancy

Ask for a limit of at least ${MAX_INSTANCES}. Approval is usually minutes to a
day. Nothing was left running, so nothing is being billed.
MSG
  else
    cat >&2 <<MSG
DEPLOY FAILED (not a quota problem).

The gcloud output above has the detail. Common causes:
  * wrong or expired credential  -> gcloud auth login
  * missing permission on the project (needs run.admin + iam.serviceAccountUser)
  * the image failed to start     -> gcloud run services logs read $CLOUD_RUN_SERVICE --region $GCP_REGION
MSG
  fi
  echo "--------------------------------------------------------------------------" >&2
  exit "$DEPLOY_RC"
fi

# --- report ----------------------------------------------------------------
SERVICE_URL=$(gcloud run services describe "$CLOUD_RUN_SERVICE" \
  --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --format="value(status.url)")

echo ""
echo "==> deployed private. Put this in .env as TAKI_BASE_URL (add /v1):"
echo "    TAKI_BASE_URL=${SERVICE_URL}/v1"
echo ""
echo "==> then verify it is locked down:  make smoke"
echo ""

# The service URL must be the last line of output.
echo "$SERVICE_URL"

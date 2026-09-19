#!/usr/bin/env bash
# Deploy the TAKI agent tier to a PRIVATE, CPU-only Cloud Run service.
#
# It reasons with Gemini on Vertex AI (this project's ADC — no key) and calls
# the private taki-mcp server. Needs:
#   * TAKI_MCP_URL              the taki-mcp service URL (from .env)
#   * roles/run.invoker on taki-mcp for this service's account
#   * roles/aiplatform.user for Vertex Gemini
# Private + IAM check enforced. Safe to re-run. Prints the URL as its last line.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
require() { [ -n "${!1:-}" ] || { echo "ERROR: $1 is not set (see .env.example)" >&2; exit 1; }; }
require GCP_PROJECT_ID; require GCP_REGION; require TAKI_MCP_URL

AGENT_SERVICE="${AGENT_SERVICE:-taki-agent}"
MCP_SERVICE="${MCP_SERVICE:-taki-mcp}"
AGENT_MODEL="${AGENT_MODEL:-gemini-2.5-flash}"
PROJECT_NUMBER=$(gcloud projects describe "$GCP_PROJECT_ID" --format="value(projectNumber)")
SA="${AGENT_SERVICE_ACCOUNT:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"

echo "=========================================================================="
echo " TAKI agent deploy (ADK, CPU only, private)"
echo " project=$GCP_PROJECT_ID region=$GCP_REGION service=$AGENT_SERVICE"
echo " model=$AGENT_MODEL (Vertex)   mcp=$TAKI_MCP_URL   runs as=$SA"
echo "=========================================================================="

echo "==> granting roles/run.invoker on '$MCP_SERVICE' + roles/aiplatform.user (idempotent)"
gcloud run services add-iam-policy-binding "$MCP_SERVICE" \
  --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --member="serviceAccount:$SA" --role="roles/run.invoker" --quiet >/dev/null
gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member="serviceAccount:$SA" --role="roles/aiplatform.user" --quiet >/dev/null

IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${AR_REPO:-taki}/${AGENT_SERVICE}:latest"
echo "==> building $IMAGE"
gcloud builds submit "$HERE" --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --tag="$IMAGE" --quiet

echo "==> deploying $AGENT_SERVICE"
gcloud run deploy "$AGENT_SERVICE" \
  --image="$IMAGE" --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --service-account="$SA" \
  --no-allow-unauthenticated \
  --invoker-iam-check \
  --port=8080 --cpu=1 --memory=1Gi --min-instances=0 --max-instances=3 --concurrency=10 --timeout=600 \
  --set-env-vars="TAKI_MCP_URL=${TAKI_MCP_URL},AGENT_MODEL=${AGENT_MODEL},GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=${GCP_PROJECT_ID},GOOGLE_CLOUD_LOCATION=${GCP_REGION},TAKI_ENV=cloudrun" \
  --quiet

URL=$(gcloud run services describe "$AGENT_SERVICE" --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --format="value(status.url)")
echo ""
echo "==> deployed private. put this in .env:   TAKI_AGENT_URL=${URL}"
echo ""
echo "$URL"

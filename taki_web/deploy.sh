#!/usr/bin/env bash
# Deploy the TAKI farmer chat UI as a PRIVATE, CPU-only Cloud Run service.
#
# It talks only to the MCP server (TAKI_MCP_URL), never to the model directly.
# Private for now: open it with `make web-open`, which proxies it to localhost
# with your own credentials. Making it public to farmers is a deliberate later
# step (IAP, or an access code) — a public page in front of a GPU is a bill.
#
# Safe to re-run. Prints the service URL as its LAST line.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE/.."
if [ -f .env ]; then set -a; . ./.env; set +a; fi
require() { [ -n "${!1:-}" ] || { echo "ERROR: $1 is not set (see .env.example)" >&2; exit 1; }; }
require GCP_PROJECT_ID; require GCP_REGION; require TAKI_MCP_URL

WEB_SERVICE="${WEB_SERVICE:-taki-web}"
MCP_SERVICE="${MCP_SERVICE:-taki-mcp}"
PROJECT_NUMBER=$(gcloud projects describe "$GCP_PROJECT_ID" --format="value(projectNumber)")
SA="${WEB_SERVICE_ACCOUNT:-${PROJECT_NUMBER}-compute@developer.gserviceaccount.com}"

echo "=========================================================================="
echo " TAKI web deploy (CPU only, private)"
echo "=========================================================================="
echo " project : $GCP_PROJECT_ID   region: $GCP_REGION"
echo " service : $WEB_SERVICE   runs as: $SA"
echo " mcp     : $TAKI_MCP_URL"
echo "=========================================================================="

echo "==> granting roles/run.invoker on '$MCP_SERVICE' to $SA (idempotent)"
gcloud run services add-iam-policy-binding "$MCP_SERVICE" \
  --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --member="serviceAccount:$SA" --role="roles/run.invoker" --quiet >/dev/null

IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${AR_REPO:-taki}/${WEB_SERVICE}:latest"
echo "==> building $IMAGE"
gcloud builds submit "$HERE" --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --tag="$IMAGE" --quiet

echo "==> deploying $WEB_SERVICE"
gcloud run deploy "$WEB_SERVICE" \
  --image="$IMAGE" --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --service-account="$SA" --no-allow-unauthenticated \
  --invoker-iam-check \
  --port=8080 --cpu=1 --memory=256Mi --min-instances=0 --max-instances=3 --concurrency=40 --timeout=600 \
  --set-env-vars="TAKI_MCP_URL=${TAKI_MCP_URL}" --quiet

URL=$(gcloud run services describe "$WEB_SERVICE" --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --format="value(status.url)")
echo ""
echo "==> deployed private. put this in .env:   TAKI_WEB_URL=${URL}"
echo "==> open it in your browser:              make web-open"
echo ""
echo "$URL"

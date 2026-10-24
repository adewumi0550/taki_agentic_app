#!/usr/bin/env bash
set -euo pipefail
gcloud run deploy underwriting-desk \
    --source underwriting_agent \
    --region "${GCP_REGION:-us-central1}" \
    --no-allow-unauthenticated \
    --set-env-vars "MCP_URL=${MCP_URL:?set MCP_URL}"

#!/usr/bin/env bash
set -euo pipefail
gcloud run deploy underwriting-mcp \
    --source underwriting_mcp \
    --region "${GCP_REGION:-us-central1}" \
    --no-allow-unauthenticated

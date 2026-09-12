"""Runtime settings for the TAKI MCP server. Everything comes from env.

No model string lives here. TAKI_MODEL_ID is injected by deploy.sh / the
Makefile from taki_model/config/models.yaml — the single source of truth.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # The private Cloud Run model service, WITH /v1 on the end.
    model_base_url: str
    # The Ollama model name to request (taki_model.name from models.yaml).
    model_id: str
    # Postgres DSN for the conversation store. Empty = logging disabled.
    db_dsn: str
    # Where this server listens.
    host: str
    port: int
    # Human-readable label for which environment this is.
    env_name: str


def load() -> Settings:
    base = os.environ.get("TAKI_BASE_URL", "").rstrip("/")
    model_id = os.environ.get("TAKI_MODEL_ID", "")
    if not base or not model_id:
        sys.exit(
            "TAKI_BASE_URL and TAKI_MODEL_ID are required.\n"
            "Run via `make mcp-local` / `make mcp-deploy`, which set both from "
            ".env and taki_model/config/models.yaml."
        )
    if not base.endswith("/v1"):
        base = base + "/v1"
    return Settings(
        model_base_url=base,
        model_id=model_id,
        db_dsn=os.environ.get("TAKI_DB_DSN", "").strip(),
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8080")),
        env_name=os.environ.get("TAKI_ENV", "local"),
    )

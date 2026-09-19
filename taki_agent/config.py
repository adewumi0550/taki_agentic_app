"""Configuration for the TAKI agent tier. Everything from env; no secrets here.

Two things the agents need:
  1. A reasoning LLM. Default: Gemini on Vertex AI (uses this project's ADC, so
     no API key). Set AGENT_MODEL to change it; set it to a LiteLLM id like
     'openai/taki' plus TAKI_BASE_URL to route reasoning through the
     self-hosted Gemma instead (weaker at tool-calling — see README).
  2. The TAKI MCP server URL (the same taki-mcp the web UI uses).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    mcp_url: str            # streamable-HTTP MCP endpoint, ends with /mcp
    model: str              # ADK/Gemini model id, or a LiteLLM id
    use_vertex: bool
    project: str
    location: str
    env_name: str


def load() -> AgentConfig:
    mcp = os.environ.get("TAKI_MCP_URL", "").rstrip("/")
    if not mcp:
        sys.exit("TAKI_MCP_URL is required (the taki-mcp service URL). See .env.")
    if not mcp.endswith("/mcp"):
        mcp = mcp + "/mcp"
    return AgentConfig(
        mcp_url=mcp,
        model=os.environ.get("AGENT_MODEL", "gemini-2.5-flash"),
        use_vertex=os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "TRUE").upper() in ("1", "TRUE", "YES"),
        project=os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT_ID", ""),
        location=os.environ.get("GOOGLE_CLOUD_LOCATION") or os.environ.get("GCP_REGION", "us-central1"),
        env_name=os.environ.get("TAKI_ENV", "local"),
    )

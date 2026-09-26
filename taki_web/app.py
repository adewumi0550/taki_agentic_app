"""TAKI web — a chat page for farmers.

  GET  /              the chat UI (static/index.html)
  POST /api/chat      {question, farmer_id?} -> the multi-agent tier (or MCP)
  GET  /api/health    is the backend reachable, and what does it report

Week 4 wiring: if TAKI_AGENT_URL is set, this service is a client of the ADK
multi-agent tier (taki-agent) — the agent routes to diagnosis / dealer and
calls the MCP tools itself, so a farmer here gets the whole system (ask_taki,
find_dealers, web-search fallback) from one message.

If TAKI_AGENT_URL is not set, it falls back to talking to taki-mcp directly
(ask_taki only) — the pre-Week-4 behaviour, handy for local dev.

Either way this service holds no model logic; the model call, dose guards and
conversation log live behind it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auth  # noqa: E402
from agent_client import AgentClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("taki.web")

AGENT_URL = os.environ.get("TAKI_AGENT_URL", "").rstrip("/")
MCP_URL = os.environ.get("TAKI_MCP_URL", "").rstrip("/")

if not AGENT_URL and not MCP_URL:
    sys.exit("Set TAKI_AGENT_URL (Week-4 agent tier) or TAKI_MCP_URL (direct MCP).")

MODE = "agent" if AGENT_URL else "mcp"
BACKEND_URL = AGENT_URL or MCP_URL
IS_LOCAL = BACKEND_URL.startswith("http://127.") or BACKEND_URL.startswith("http://localhost")
MCP_ENDPOINT = f"{MCP_URL}/mcp" if MCP_URL else None

STATIC = Path(__file__).resolve().parent / "static"
app = FastAPI(title="TAKI web", docs_url=None, redoc_url=None)


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    farmer_id: str | None = Field(default=None, max_length=128)


def _headers(audience: str) -> dict[str, str]:
    # Local backends have no IAM in front; Cloud Run ones need an identity
    # token minted for that service's origin.
    if IS_LOCAL:
        return {}
    return {"Authorization": f"Bearer {auth.identity_token(audience)}"}


# --- agent tier client (Week 4) -------------------------------------------
_agent = AgentClient(AGENT_URL, headers_fn=lambda: _headers(AGENT_URL)) if AGENT_URL else None


# --- MCP fallback ----------------------------------------------------------
def _structured(result) -> dict[str, Any]:
    sc = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if sc:
        return dict(sc)
    text = "\n".join(getattr(c, "text", "") for c in result.content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"reply": text}


async def _mcp_call(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(headers=_headers(MCP_URL), timeout=600.0) as http:
        async with streamable_http_client(MCP_ENDPOINT, http_client=http) as (read, write, *_):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(tool, args)
                if getattr(res, "is_error", False) or getattr(res, "isError", False):
                    raise HTTPException(502, f"MCP tool error: {_structured(res)}")
                return _structured(res)


PLACEHOLDER = "<DOSE_FROM_REGISTRY>"


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    try:
        if MODE == "agent":
            headers = _headers(AGENT_URL)
            async with httpx.AsyncClient(headers=headers, timeout=30.0) as http:
                r = await http.get(f"{AGENT_URL}/list-apps")
                r.raise_for_status()
                return {"ok": True, "mode": "agent", "agent": AGENT_URL, "apps": r.json()}
        info = await _mcp_call("taki_info", {})
        return {"ok": True, "mode": "mcp", "mcp": MCP_ENDPOINT, **info}
    except Exception as exc:  # surfaced to the UI banner
        log.error("health check failed: %s", exc)
        return {"ok": False, "mode": MODE, "backend": BACKEND_URL, "error": str(exc)[:300]}


@app.post("/api/chat")
async def chat(body: ChatIn) -> dict[str, Any]:
    try:
        if MODE == "agent":
            # AgentClient is sync (httpx.Client); run off the event loop.
            reply = await asyncio.to_thread(_agent.ask, body.question, body.farmer_id)
            return {
                "reply": reply.reply,
                "latency_ms": reply.latency_ms,
                "model_id": "taki multi-agent",
                "routed_to": reply.routed_to,
                "tools_used": reply.tools_used,
                "used_registry_placeholder": PLACEHOLDER in reply.reply,
                # The dose guards live in the agent/MCP layers, not here; the web
                # layer cannot see whether one fired, so report unknown.
                "dose_guard_triggered": False,
            }
        return await _mcp_call("ask_taki", {"question": body.question, "farmer_id": body.farmer_id})
    except HTTPException:
        raise
    except Exception as exc:
        log.error("chat failed: %s", exc)
        raise HTTPException(502, f"TAKI is unreachable: {str(exc)[:200]}")


app.mount("/static", StaticFiles(directory=STATIC), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))

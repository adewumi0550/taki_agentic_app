"""TAKI web — a chat page for farmers, backed by the MCP server.

  GET  /              the chat UI (static/index.html)
  POST /api/chat      {question, farmer_id?} -> ask_taki via MCP
  GET  /api/health    is the MCP server reachable, and what does it report

This service holds no model logic. It is an MCP client of taki-mcp, which is
where the model call, the runtime dose guard and the conversation store live.
That means there is exactly one path from a farmer to the model, and it is
guarded.
"""
from __future__ import annotations

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

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("taki.web")

MCP_URL = os.environ.get("TAKI_MCP_URL", "").rstrip("/")
if not MCP_URL:
    sys.exit("TAKI_MCP_URL is required (run via `make web-local` / `make web-deploy`).")
MCP_ENDPOINT = f"{MCP_URL}/mcp"
IS_LOCAL_MCP = MCP_URL.startswith("http://127.") or MCP_URL.startswith("http://localhost")

STATIC = Path(__file__).resolve().parent / "static"
app = FastAPI(title="TAKI web", docs_url=None, redoc_url=None)


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    farmer_id: str | None = Field(default=None, max_length=128)


def _headers() -> dict[str, str]:
    # Local MCP has no IAM in front; Cloud Run MCP needs an identity token
    # minted for this service's account.
    return {} if IS_LOCAL_MCP else {"Authorization": f"Bearer {auth.identity_token(MCP_URL)}"}


def _structured(result) -> dict[str, Any]:
    sc = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if sc:
        return dict(sc)
    text = "\n".join(getattr(c, "text", "") for c in result.content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"reply": text}


async def _call(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(headers=_headers(), timeout=600.0) as http:
        async with streamable_http_client(MCP_ENDPOINT, http_client=http) as (read, write, *_):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(tool, args)
                if getattr(res, "is_error", False) or getattr(res, "isError", False):
                    raise HTTPException(502, f"MCP tool error: {_structured(res)}")
                return _structured(res)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    try:
        info = await _call("taki_info", {})
        return {"ok": True, "mcp": MCP_ENDPOINT, **info}
    except Exception as exc:  # surfaced to the UI banner
        log.error("health check failed: %s", exc)
        return {"ok": False, "mcp": MCP_ENDPOINT, "error": str(exc)[:300]}


@app.post("/api/chat")
async def chat(body: ChatIn) -> dict[str, Any]:
    try:
        return await _call("ask_taki", {"question": body.question, "farmer_id": body.farmer_id})
    except HTTPException:
        raise
    except Exception as exc:
        log.error("chat failed: %s", exc)
        raise HTTPException(502, f"TAKI is unreachable: {str(exc)[:200]}")


app.mount("/static", StaticFiles(directory=STATIC), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))

#!/usr/bin/env python3
"""Smoke test for the TAKI MCP server, as a real MCP client.

  1. initialize + list tools over streamable HTTP with an identity token
  2. call taki_info  (model, store status)
  3. call ask_taki   with a Hausa greeting, print the reply and timing
  4. NEGATIVE: the same POST with no Authorization header must be rejected
     (403 on Cloud Run). Skipped for localhost, which has no IAM in front.

  python taki_mcp/smoke_test.py http://localhost:8090
  python taki_mcp/smoke_test.py https://taki-mcp-....run.app
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auth  # noqa: E402

QUESTION = "Sannu, yaya kake?"


def _content_text(result) -> str:
    sc = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if sc:
        return json.dumps(sc, ensure_ascii=False, indent=2)
    return "\n".join(getattr(c, "text", "") for c in result.content)


async def main(base: str) -> int:
    base = base.rstrip("/")
    url = f"{base}/mcp"
    is_local = base.startswith("http://localhost") or base.startswith("http://127.")
    headers = {} if is_local else {"Authorization": f"Bearer {auth.identity_token(base)}"}

    print("=" * 74)
    print(f" TAKI MCP smoke test   {url}")
    print("=" * 74)

    async with httpx.AsyncClient(headers=headers, timeout=600.0) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, *_):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                print("tools   :", ", ".join(t.name for t in tools.tools))

                info = await session.call_tool("taki_info", {})
                print("info    :", _content_text(info).replace("\n", "\n          "))

                print(f"\nask_taki: {QUESTION!r}")
                t0 = time.perf_counter()
                res = await session.call_tool("ask_taki", {"question": QUESTION, "farmer_id": "smoke"})
                dt = time.perf_counter() - t0
                if getattr(res, "is_error", False) or getattr(res, "isError", False):
                    print("TOOL ERROR:", _content_text(res)); return 1
                print("-" * 74)
                print(_content_text(res))
                print("-" * 74)
                print(f"round trip through MCP: {dt:.2f}s")

    if is_local:
        print("\nnegative test skipped on localhost (no IAM in front of a local port)")
        return 0

    print("\nNEGATIVE: same endpoint, no Authorization header")
    r = httpx.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   headers={"Content-Type": "application/json",
                            "Accept": "application/json, text/event-stream"}, timeout=30)
    print(f"  HTTP {r.status_code}")
    if r.status_code in (401, 403):
        print("  PASS — unauthenticated request rejected. MCP endpoint is private.")
        return 0
    print("  FAIL — endpoint answered without auth. It may be PUBLIC. Fix now:")
    print(f"    gcloud run services remove-iam-policy-binding taki-mcp --member=allUsers --role=roles/run.invoker")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8090")))

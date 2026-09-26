"""Client for the TAKI agent tier (ADK api_server).

This is the Week-4 connection: the farmer web UI talks to the multi-agent
system (taki-agent) instead of calling MCP directly. The agent does the
routing — diagnosis vs dealer — and calls the MCP tools itself, so a farmer on
the web now gets the whole system (ask_taki, find_dealers, web-search fallback)
from one message.

ADK's api_server REST surface (verified against google-adk 2.9.2):
  POST /apps/{app}/users/{user}/sessions   -> create a session (auto id)
  POST /run  {app_name,user_id,session_id,new_message} -> list[Event]

The final farmer-facing answer is the last model text event in that list.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

APP_NAME = "taki_agent"  # ADK discovers the package dir by this name


@dataclass
class AgentReply:
    reply: str
    latency_ms: int
    routed_to: str | None       # which sub-agent produced the answer
    tools_used: list[str]


def _final_text_and_trace(events: list[dict[str, Any]]) -> tuple[str, str | None, list[str]]:
    final, author, tools = "", None, []
    for ev in events:
        content = ev.get("content") or {}
        parts = content.get("parts") or []
        for p in parts:
            fc = p.get("functionCall") or p.get("function_call")
            if fc and fc.get("name"):
                tools.append(fc["name"])
        text = "".join(p.get("text", "") for p in parts if p.get("text"))
        # the farmer-facing answer is model-authored text (not a tool call)
        if text and content.get("role") == "model":
            final = text
            author = ev.get("author") or author
    return final.strip(), author, tools


class AgentClient:
    def __init__(self, base_url: str, headers_fn):
        # base_url is the taki-agent service origin (no trailing slash)
        self.base = base_url.rstrip("/")
        self._headers_fn = headers_fn  # () -> dict, mints identity token per call

    def ask(self, question: str, farmer_id: str | None = None,
            timeout: float = 600.0) -> AgentReply:
        user = farmer_id or "web-anon"
        started = time.perf_counter()
        with httpx.Client(timeout=timeout) as http:
            headers = self._headers_fn()
            # 1. create a session (fresh per message — stateless, scale-to-zero friendly)
            s = http.post(
                f"{self.base}/apps/{APP_NAME}/users/{user}/sessions",
                headers=headers, json={},
            )
            s.raise_for_status()
            session_id = s.json()["id"]

            # 2. run the agent on the farmer's message
            r = http.post(
                f"{self.base}/run",
                headers=headers,
                json={
                    "app_name": APP_NAME,
                    "user_id": user,
                    "session_id": session_id,
                    "new_message": {"role": "user", "parts": [{"text": question}]},
                },
            )
            r.raise_for_status()
            events = r.json()

        latency_ms = int((time.perf_counter() - started) * 1000)
        text, author, tools = _final_text_and_trace(events)
        return AgentReply(reply=text, latency_ms=latency_ms, routed_to=author, tools_used=tools)

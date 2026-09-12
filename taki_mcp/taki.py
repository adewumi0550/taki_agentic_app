"""ask_taki — the one function every caller goes through.

MCP tool, web UI, anything else: they all land here. This is where the model
is called, where the runtime dose guard runs on the reply, and where the
exchange is written to the conversation store. Keep it that way — a second
path to the model is a path without the guard.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from typing import Any

import httpx

import auth
import guard
from db import Store
from settings import Settings


@dataclass
class Answer:
    reply: str
    conversation_id: int | None
    model_id: str
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    used_registry_placeholder: bool
    dose_guard_triggered: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class Taki:
    def __init__(self, settings: Settings, store: Store):
        self.s = settings
        self.store = store
        # The model service is a private Cloud Run URL; the audience for the
        # identity token is the service origin, not the /v1 path.
        self._audience = settings.model_base_url.removesuffix("/v1")
        self._http = httpx.Client(timeout=httpx.Timeout(600.0, connect=30.0))

    def ask(self, question: str, *, channel: str, farmer_id: str | None = None,
            temperature: float = 0.3) -> Answer:
        question = (question or "").strip()
        if not question:
            raise ValueError("question is empty")

        # --- model call: OpenAI-compatible, same wire format as everywhere else
        started = time.perf_counter()
        r = self._http.post(
            f"{self.s.model_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {auth.identity_token(self._audience)}"},
            json={
                "model": self.s.model_id,
                "messages": [{"role": "user", "content": question}],
                "temperature": temperature,
            },
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        if r.status_code != 200:
            raise RuntimeError(f"model service returned HTTP {r.status_code}: {r.text[:300]}")
        body = r.json()
        raw = (body["choices"][0]["message"]["content"] or "").strip()
        usage = body.get("usage") or {}

        # --- runtime dose guard on what the farmer will actually see
        g = guard.apply(raw)

        # --- conversation store (best effort; never blocks the answer)
        conv_id = self.store.insert({
            "channel": channel,
            "farmer_id": farmer_id,
            "question": question,
            "reply": g.text,
            "model_id": self.s.model_id,
            "model_url": self.s.model_base_url,
            "latency_ms": latency_ms,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "used_registry_placeholder": guard.PLACEHOLDER in g.text,
            "dose_guard_triggered": g.triggered,
            "dose_guard_matches": list(g.matches) or None,
            "env_name": self.s.env_name,
        })

        return Answer(
            reply=g.text,
            conversation_id=conv_id,
            model_id=self.s.model_id,
            latency_ms=latency_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            used_registry_placeholder=guard.PLACEHOLDER in g.text,
            dose_guard_triggered=g.triggered,
        )

"""Output-side dose guard for the agent tier.

The MCP server guards what the MODEL says. But once the dealer agent can read
the open web (google_search), untrusted text enters the agent tier that never
passes through taki-mcp — a web page could list an application rate and the
agent could echo it. This is the last net: an ADK `after_model_callback` that
redacts anything dose-shaped from the agent's OWN output before it reaches the
farmer.

The patterns MUST stay in sync with taki_mcp/guard.py (the model-side guard).
Both are covered by scripts/check_no_doses.sh, which forbids literal doses in
the repo, so these are built from character classes, not real numbers.
"""
from __future__ import annotations

import logging
import re

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmResponse

log = logging.getLogger("taki.agent.dose_guard")

PLACEHOLDER = "<DOSE_FROM_REGISTRY>"

_NUM = r"\d[\d.,]*"
_SP = r"\s*"
_PER = r"(?:/|per\s+|a\s+kowace\s+|kowane\s+)"
_PATTERNS = [
    rf"{_NUM}{_SP}(?:ml|mL|cc|l|L|lita|litre|liter)s?{_SP}{_PER}{_SP}(?:l|L|lita|litre|liter|drum|gal(?:lon)?|ruwa)",
    rf"{_NUM}{_SP}(?:g|kg|gram|grams|kilo)s?{_SP}{_PER}{_SP}(?:l|L|lita|litre|liter|ha|hectare|hekta|acre|kadada)",
    rf"{_NUM}{_SP}(?:ml|mL|l|L|lita|litre|liter)s?{_SP}{_PER}{_SP}(?:ha|hectare|hekta|acre|kadada)",
    rf"{_NUM}{_SP}(?:sachet|capful|cap|tablespoon|teaspoon|cokali|murfi)s?{_SP}{_PER}",
    rf"{_NUM}{_SP}(?:days?|kwanaki|kwana|hours?|awa|sa'o'i)\s+(?:before|kafin|pre-?)\s*(?:harvest|girbi|re-?entry|shiga)",
    rf"(?:pre-?harvest|re-?entry)\s+interval\D{{0,12}}{_NUM}",
]
_RX = [re.compile(p, re.IGNORECASE) for p in _PATTERNS]


def redact(text: str) -> tuple[str, bool]:
    hit = False
    out = text
    for rx in _RX:
        out, n = rx.subn(PLACEHOLDER, out)
        hit = hit or bool(n)
    return out, hit


def after_model_dose_guard(callback_context: CallbackContext,
                           llm_response: LlmResponse) -> LlmResponse | None:
    """Redact dose-shaped text from a model response. Returns it only if changed."""
    if not llm_response or not llm_response.content or not llm_response.content.parts:
        return None
    changed = False
    for part in llm_response.content.parts:
        if getattr(part, "text", None):
            new, hit = redact(part.text)
            if hit:
                part.text = new
                changed = True
                log.warning("output dose guard redacted a rate in agent output")
    return llm_response if changed else None

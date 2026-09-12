"""TAKI MCP server.

Exposes the model to agents as MCP tools over streamable HTTP. Deployed as a
private, CPU-only Cloud Run service; callers present a Google identity token.

Tools
  ask_taki             ask a farming question, get the guarded Hausa/English reply
  taki_info            model, backend, conversation-store status
  recent_conversations read back the conversation store (audit / debugging)
  find_dealers         look up VERIFIED agro-input sellers by location

Run locally:   make mcp-local        (streamable HTTP on :8090)
Run on Cloud:  make mcp-deploy
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settings as _settings  # noqa: E402
from db import Store  # noqa: E402
from dealers import DealerStore  # noqa: E402
from taki import Taki  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("taki.mcp")

S = _settings.load()
STORE = Store(S.db_dsn)
DEALERS = DealerStore(S.db_dsn)
TAKI = Taki(S, STORE)
DB_STATUS = STORE.ensure_schema()
DEALER_STATUS = DEALERS.ensure_schema()
log.info("model=%s url=%s store=%s dealers=%s", S.model_id, S.model_base_url, DB_STATUS, DEALER_STATUS)

mcp = MCPServer(
    name="taki",
    title="TAKI — agrochemical advisory for northern Nigeria",
    instructions=(
        "TAKI answers smallholder farming questions in Hausa or English: pest "
        "symptoms, crop timing, general practice. It never gives a pesticide "
        "dose, mixing ratio, pre-harvest interval or re-entry interval; where "
        "one belongs it returns the placeholder <DOSE_FROM_REGISTRY> and refers "
        "the farmer to the product label. Do not try to fill that placeholder "
        "yourself. Pass the farmer's words through unchanged, in their language."
    ),
)


@mcp.tool(
    name="ask_taki",
    description=(
        "Ask TAKI a farming question in Hausa or English. Returns the reply plus "
        "latency, token counts, and whether the dose guard fired. The reply may "
        "contain <DOSE_FROM_REGISTRY>; leave it in place."
    ),
)
def ask_taki(question: str, farmer_id: str | None = None) -> dict[str, Any]:
    return TAKI.ask(question, channel="mcp", farmer_id=farmer_id).as_dict()


@mcp.tool(
    name="taki_info",
    description="Which model TAKI is running, where, and whether the conversation store is up.",
)
def taki_info() -> dict[str, Any]:
    return {
        "model_id": S.model_id,
        "model_url": S.model_base_url,
        "env": S.env_name,
        "conversation_store": STORE.ensure_schema(),
        "dealer_directory": DEALERS.ensure_schema(),
        "guard": "runtime dose guard active on every reply",
    }


@mcp.tool(
    name="recent_conversations",
    description=(
        "Read the most recent conversations from the store (newest first). "
        "Set only_guard_hits=true to see only replies where the dose guard redacted something."
    ),
)
def recent_conversations(limit: int = 10, only_guard_hits: bool = False) -> dict[str, Any]:
    rows = STORE.recent(limit=limit, only_guard_hits=only_guard_hits)
    return {"store": DB_STATUS if STORE.enabled else "disabled", "count": len(rows), "rows": rows}


@mcp.tool(
    name="find_dealers",
    description=(
        "Find VERIFIED agro-input / pesticide sellers near a location (town, LGA "
        "or state, e.g. 'Kano'). Optionally filter by product_class (e.g. "
        "'insecticide'). Returns only sellers a human has verified in the "
        "directory; if none are loaded for that area it returns an empty list. "
        "It never invents a seller — an empty result means 'no verified dealer on "
        "record here', which the caller should relay honestly (e.g. suggest the "
        "local extension officer)."
    ),
)
def find_dealers(location: str, product_class: str | None = None, limit: int = 10) -> dict[str, Any]:
    rows = DEALERS.find(location, product_class=product_class, limit=limit)
    return {
        "directory": DEALER_STATUS if DEALERS.enabled else "disabled",
        "location": location,
        "product_class": product_class,
        "count": len(rows),
        "dealers": rows,
        "note": (
            "No verified seller on record for this area — do not guess one; "
            "refer the farmer to their local extension officer or agro-dealer."
            if not rows else None
        ),
    }


# Cloud Run IAM is the auth boundary, and the Host header there is the
# *.run.app domain — so the SDK's DNS-rebinding check must not reject it.
app = mcp.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,       # no sticky sessions; safe behind Cloud Run's load balancer
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


if __name__ == "__main__":
    uvicorn.run(app, host=S.host, port=S.port, log_level="info")

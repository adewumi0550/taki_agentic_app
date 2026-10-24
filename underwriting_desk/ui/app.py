"""The money desk, one process.

The MCP server is MOUNTED into this app rather than spawned beside it, so
there is no subprocess to die and no second port to coordinate. The agents
still reach their tools over MCP/HTTP -- the boundary is real, it just
happens to be the same process in this deployment.

Local:      ../.venv-agent/bin/python ui/app.py     -> http://127.0.0.1:8099
Cloud Run:  Procfile runs uvicorn against main:app
"""
import json
import os
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BUDGETS = Path(os.environ.get("BUDGET_DIR", ROOT / "budgets"))
BUDGETS.mkdir(parents=True, exist_ok=True)

PORT = int(os.environ.get("PORT", "8099"))
HOST = os.environ.get("HOST", "127.0.0.1")

# The agents read MONEY_MCP_URL at import, so point it at our own mount first.
MCP_MOUNT = "/mcpsrv"
os.environ.setdefault("MONEY_MCP_URL", f"http://127.0.0.1:{PORT}{MCP_MOUNT}/mcp")

from fastapi import FastAPI, Request                        # noqa: E402
from fastapi.responses import FileResponse, JSONResponse    # noqa: E402
from ag_ui_adk import ADKAgent, add_adk_fastapi_endpoint     # noqa: E402

import money_mcp                                            # noqa: E402
import agents                                               # noqa: E402

mcp_app = money_mcp.mcp.streamable_http_app()

# FastMCP's session manager lives in its own lifespan; adopt it or the
# mounted routes 500 on first request.
app = FastAPI(title="money-desk", lifespan=mcp_app.router.lifespan_context)
app.mount(MCP_MOUNT, mcp_app)


@app.get("/health")
def health():
    return {"ok": True, "agents": list(agents.SPECS)}


@app.post("/budget")
async def budget(req: Request):
    """Store a submitted split and hand back its id, like a loan file_id."""
    body = await req.json()
    income = int(body.get("income") or 0)
    alloc = {k: int(v) for k, v in (body.get("alloc") or {}).items()}
    if income <= 0 or not alloc:
        return JSONResponse({"error": "income and alloc required"}, status_code=400)
    bid = "b" + uuid.uuid4().hex[:10]
    (BUDGETS / f"{bid}.json").write_text(json.dumps({
        "budget_id": bid, "name": body.get("name", ""), "income": income,
        "alloc": alloc, "ts": time.time(),
    }, indent=2))
    return {"budget_id": bid}


@app.get("/")
def page():
    return FileResponse(HERE / "money_desk.html")


add_adk_fastapi_endpoint(
    app,
    ADKAgent(adk_agent=agents.root_agent, app_name="money_desk",
             user_id="demo", use_in_memory_services=True),
    path="/agui",
)


if __name__ == "__main__":
    import uvicorn
    print(f"\n  money desk  ->  http://127.0.0.1:{PORT}\n")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")

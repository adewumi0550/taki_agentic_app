"""The money desk, served locally.

One process: starts the MCP server, mounts the ADK agent behind an AG-UI
endpoint, and serves the page from the SAME origin so the browser can
stream from it.

    ../.venv-agent/bin/python ui/app.py      ->  http://127.0.0.1:8099
"""
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BUDGETS = ROOT / "budgets"
BUDGETS.mkdir(exist_ok=True)
sys.path.insert(0, str(HERE))

MCP_PORT = int(os.environ.get("MCP_PORT", "8787"))
PORT = int(os.environ.get("PORT", "8099"))
os.environ.setdefault("MONEY_MCP_URL", f"http://127.0.0.1:{MCP_PORT}/mcp")

from fastapi import FastAPI, Request          # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402

from ag_ui_adk import ADKAgent, add_adk_fastapi_endpoint  # noqa: E402

import agents  # noqa: E402

app = FastAPI(title="money-desk")


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


def start_mcp() -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "money_mcp.py")],
        env={**os.environ, "MCP_PORT": str(MCP_PORT)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(100):
        if proc.poll() is not None:
            raise SystemExit("money-desk MCP failed to start")
        with socket.socket() as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", MCP_PORT)) == 0:
                return proc
        time.sleep(0.1)
    proc.terminate()
    raise SystemExit(f"MCP did not come up on :{MCP_PORT}")


if __name__ == "__main__":
    import uvicorn
    mcp = start_mcp()
    print(f"\n  money desk  ->  http://127.0.0.1:{PORT}\n")
    try:
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
    finally:
        mcp.terminate()

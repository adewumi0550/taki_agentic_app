# The Money Desk — UI

A gamified demo for DevFest Owerri 2026. Open an account, split your
income, and four ADK agents review the split at the same time.

## Run it live (agents on)

```bash
cd /Users/adewumi0550/Desktop/taki
set -a; source .env; set +a
.venv-agent/bin/python underwriting_desk/ui/app.py
# -> http://127.0.0.1:8099
```

`app.py` starts `money_mcp.py` itself, mounts `agents.py` behind an AG-UI
endpoint at `/agui`, and serves `money_desk.html` from the same origin —
which is what lets the browser stream from it. A green **● LIVE AGENTS**
pill appears in the header when the page finds the backend.

| file | what it is |
|---|---|
| `money_desk.html` | the whole UI, one file, no build step |
| `money_mcp.py` | FastMCP server: 4 budget tools, rules + log inside |
| `agents.py` | 4 `LlmAgent`s, `tool_filter`-scoped, in a `ParallelAgent` |
| `app.py` | FastAPI: `/` page, `POST /budget`, `/agui`, `/health` |

## How the UI knows which agent said what

AG-UI's `TEXT_MESSAGE_START` carries no agent name. The attribution comes
from `STATE_DELTA`: each specialist's `output_key` arrives as a JSON-patch
op on `/budget_agent`, `/savings_agent`, `/policy_agent`, `/risk_agent`,
and the reconciler's closing note on `/memo`. `TOOL_CALL_START` lights a
lane early, mapped tool name -> agent.

## Fallback

Opened anywhere the backend is not reachable — the published artifact
included — the `/health` probe fails and the page computes the same
numbers locally from the same benchmarks. The demo cannot go dark.

Ticking **"Run the agents one at a time"** always uses the local path, so
the concurrent-vs-sequential comparison stays instant on stage.

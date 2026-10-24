# Build prompt — Multi-Agent Underwriting Desk

Paste this into a coding agent to build the project from zero, or to
extend the existing scaffold. Everything below is verified against
working code, not recalled.

---

## The project

Build a **credit underwriting desk**: four specialist agents read one
loan file concurrently, and a reconciler turns what they found into a
decision memo a human signs. The system never approves anything — it
drafts, a credit officer signs.

It is three layers, deliberately separated:

- **`underwriting_mcp/`** — a FastMCP server holding the four tools.
  Every rule is enforced here and every call is logged here.
- **`underwriting_agent/`** — Google ADK agents. They reason; they act
  only through MCP.
- **`underwriting_ui/`** — an AG-UI endpoint so a browser front end can
  stream the run.

The split is the point: the agents can be replaced wholesale and every
guard and every audit line still applies, because they do not live in
the agent.

## Target folder structure

```
underwriting_desk/
├── README.md
├── requirements.txt
├── .env.example
├── run_desk.py                 # local end-to-end runner (CLI)
├── fixtures/
│   ├── clean_file.json         # runs clean -> APPROVE
│   └── conflict_file.json      # built to make two agents disagree
├── underwriting_mcp/
│   ├── server.py               # FastMCP app, 4 tools
│   ├── guard.py                # credit rules, enforced server-side
│   ├── audit.py                # decision log, written BEFORE return
│   ├── tools/
│   │   ├── statements.py
│   │   ├── identity.py
│   │   ├── collateral.py
│   │   └── policy.py
│   └── deploy.sh
├── underwriting_agent/
│   ├── agent.py                # ParallelAgent inside SequentialAgent
│   ├── specialists.py          # the four LlmAgents
│   ├── reconciler.py           # precedence / evidence / escalation
│   ├── mcp_toolset.py          # tool_filter-scoped MCPToolset
│   └── deploy.sh
└── underwriting_ui/
    ├── app.py                  # FastAPI + AG-UI endpoint
    └── deploy.sh
```

## Versions (checked on PyPI, pin these)

```
google-adk>=2.9.2
mcp>=1.30.0
ag-ui-adk>=0.11.0        # requires google-adk >= 1.28.1
ag-ui-protocol>=1.0.0
fastapi
uvicorn
```

---

## Part 1 — FastMCP server and tools

Use `mcp.server.fastmcp.FastMCP`. Construct it with host/port from the
environment and `stateless_http=True`, then
`mcp.run(transport="streamable-http")`. The streamable-HTTP path is
`/mcp` by default, so the agent's URL is `http://host:port/mcp`.

Expose exactly four tools, each taking `file_id: str` and returning a
dict:

| tool | returns |
|---|---|
| `read_statements` | inflow volatility, salary regularity, overdraft days, `dscr` |
| `verify_identity` | name/address match, sanctions hit |
| `value_collateral` | title clean, valuation, existing charges |
| `check_policy` | the result of `guard.enforce_policy` |

Non-negotiable in this layer:

1. **Every returned dict carries a `source` field** naming the document
   it came from. The reconciler drops unsourced findings, so a tool that
   forgets a source silently deletes its own finding from the memo.
2. **`guard.py` holds the credit rules** — exposure ceiling, excluded
   sectors, minimum DSCR — and `check_policy` runs them. Rules must not
   live in any prompt. Return breaches as readable strings
   (`"dscr_below_minimum: 0.74 is under 1.25"`), not bare codes.
3. **`audit.py` appends to `decision_log.jsonl` before the tool returns
   its result.** There must be no code path where a tool ran and nothing
   was recorded.
4. Tools read **synthetic fixtures only**. No real applicant data, ever.

## Part 2 — Google ADK agents

Imports that are correct for ADK 2.9.x:

```python
from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.mcp_tool import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.runners import InMemoryRunner
```

**Specialists.** Build all four from one factory. Each gets its own
domain brief, `output_key=<its name>`, and a toolset scoped to exactly
one tool:

```python
MCPToolset(
    connection_params=StreamableHTTPConnectionParams(url=MCP_URL, headers=headers),
    tool_filter=["read_statements"],
)
```

`tool_filter` is the safety story — the agent cannot *see* the other
tools, rather than being asked not to call them.

**Set `disallow_transfer_to_parent=True` and
`disallow_transfer_to_peers=True` on every specialist.** Inside a
`ParallelAgent` the siblings are peers, and without these an agent will
sometimes hand off instead of calling its tool, then report nothing.

**Orchestration** is two objects:

```python
evidence = ParallelAgent(name="evidence", sub_agents=all_specialists())
desk = SequentialAgent(name="underwriting_desk", sub_agents=[evidence, reconciler])
```

No specialist may read another's state key. If one does, the
concurrency is a lie and you have a pipeline.

**Reconciler.** Give `instruction` a *callable*
(`Callable[[ReadonlyContext], str]`), not a template string — read the
four `output_key`s off `ctx.state` yourself and format them in. Missing
keys then degrade instead of raising. Its rules, applied in order:

1. **Precedence** — a policy breach outranks a favourable valuation,
   always. A failing DSCR is not cured by strong collateral.
2. **Evidence** — every memo line names the agent and the source
   document. Unsourced findings are dropped, and the memo says so.
3. **Name every conflict** — if two specialists point in opposite
   directions, list it under CONFLICTS *even when precedence already
   settles the outcome*. Only mark the memo ESCALATED when no rule
   resolves it. Never average, never pick the more confident one.
4. **Missing input** — if a specialist is absent or errored, write
   INCOMPLETE at the top and name the missing check. Never ship a memo
   that silently omits one.

Fixed output shape: `RECOMMENDATION / WHY / FINDINGS / CONFLICTS /
FOR THE CREDIT OFFICER`.

**Auth.** Against Cloud Run, attach `Authorization: Bearer <identity
token>` (`google.oauth2.id_token.fetch_id_token`, audience = the service
URL without the `/mcp` path). Against localhost, send no header. Note in
a comment that tokens last ~1h, so a long-lived service must refresh per
call rather than capturing once at toolset construction.

**Also build `build_sequential_desk()`** — the same four specialists in
a `SequentialAgent` — so the concurrent-vs-sequential timing can be
measured on identical work.

## Part 3 — AG-UI layer

`ag-ui-adk` is the Python middleware that translates the ADK event
stream into AG-UI protocol events and serves them over FastAPI, so any
AG-UI-compatible front end can drive the desk. It is Python-only; there
is no TypeScript ADK middleware.

```python
from ag_ui_adk import ADKAgent, add_adk_fastapi_endpoint
from fastapi import FastAPI
from agent import build_desk

app = FastAPI()
add_adk_fastapi_endpoint(app, ADKAgent(adk_agent=build_desk()), path="/")
```

Check the installed package's own signatures before wiring it —
`ADKAgent`'s keyword arguments have moved between 0.x releases.

What the front end must show, because it is what makes the talk's point
visible:

- **Four agents starting at once.** Stream tool-call events per agent so
  the UI can show four lanes lighting up together, not a progress bar.
- **Every finding with its citation**, rendered as text the reader can
  click back to the source document.
- **Conflicts, surfaced not smoothed.** When the memo is ESCALATED the
  UI shows both findings side by side and asks the human to choose.
- **A sign / send-back control.** The desk drafts; the officer decides.
  Do not build an "auto-approve" path.

---

## Definition of done

```bash
make demo        # clean_file   -> APPROVE,  4/4 specialists reporting
make conflict    # conflict_file -> DECLINE, conflict named under CONFLICTS
make timing      # concurrent, then sequential, on the same file
make ui          # AG-UI endpoint, browser shows four lanes in parallel
```

- `run_desk.py` starts the MCP server itself — nothing to launch in a
  second terminal.
- Trace prints per-agent start offsets. Concurrent runs cluster within
  ~1s; sequential runs form a staircase.
- `decision_log.jsonl` has one line per tool call.
- Both `deploy.sh` scripts use `--no-allow-unauthenticated`, and a smoke
  test asserts an unauthenticated request is rejected.
- Nothing in the system can approve a loan.

## Known traps

These all bit a real build of this project:

1. A specialist **answered without calling its tool** and contributed
   nothing — fixed by the `disallow_transfer_*` flags above.
2. The **policy breach was dropped** by the reconciler's own evidence
   rule because `check_policy` returned no `source` field. The single
   most important finding vanished from a memo that still looked
   complete. This is the partial-failure mode worth demoing.
3. The reconciler **wrote "CONFLICTS: none"** while correctly declining
   on precedence — it resolved the conflict, so by its own rules it said
   nothing about it. Hence rule 3 above.
4. Expect roughly **2x** from four agents, not 4x. You wait for the
   slowest specialist, and the reconciler is serial and expensive.

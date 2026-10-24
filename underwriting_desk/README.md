# underwriting_desk

A credit underwriting desk: four ADK specialists read one loan file
concurrently, and a reconciler turns what they found into a memo a human
signs. Built for the DevFest Owerri 2026 talk on when multi-agent is
worth it -- and when it is not.

Two projects. The agents reason; the MCP server acts.

```
underwriting_agent/   four specialists + a reconciler      -> Cloud Run
underwriting_mcp/     the four tools, guarded and logged   -> Cloud Run
fixtures/             synthetic loan files (no real data)
run_desk.py           runs the whole thing locally
```

They communicate over MCP: `underwriting_agent/mcp_toolset.py` reads
`MCP_URL` and calls `underwriting_mcp/server.py`. Against Cloud Run it
attaches a bearer identity token; against localhost it does not.

## Run it

```bash
cp .env.example .env     # fill in GOOGLE_CLOUD_PROJECT
make demo                # clean file -> APPROVE
make conflict            # conflicting file -> DECLINE, conflict named
make timing              # concurrent, then sequential
```

`run_desk.py` starts the MCP server itself, so there is nothing to
launch in another terminal.

## What actually works

Both fixtures run end to end against Gemini on Vertex AI. Measured
numbers are in [TIMINGS.md](TIMINGS.md) -- concurrent 18.6s against
sequential 36.6s, a 1.97x speedup rather than 4x.

- `underwriting_mcp/guard.py` enforces exposure, sector and DSCR limits
  **in the server**, so no prompt can talk an agent past them.
- `underwriting_mcp/audit.py` writes `decision_log.jsonl` **before** a
  tool result is returned. There is no path where a tool ran and nothing
  was recorded.
- Each specialist gets exactly one tool via `tool_filter`, and cannot
  transfer to a peer.
- The reconciler applies precedence, then evidence, then escalation, and
  names every material conflict even when precedence settles the outcome.

## Not done

Cloud Run deployment is scripted (`*/deploy.sh`, both
`--no-allow-unauthenticated`) but has not been run. The identity token is
captured once at toolset construction; tokens last about an hour, so a
long-lived service must refresh per call.

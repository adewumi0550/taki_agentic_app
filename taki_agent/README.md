# taki_agent — ADK multi-agent tier

A multi-agent system built on Google's **Agent Development Kit (ADK)**. The
agents **reason with Gemini** (Vertex AI) and **act only through the TAKI MCP
server**. They never touch the model or the database directly, so the dose
guard and the conversation log that live in `taki-mcp` sit on every answer —
the agent layer cannot bypass them.

```
                       ┌────────────────────────────────────────┐
  farmer message  ──►  │  taki_root (LlmAgent, Gemini)           │
                       │    routes by intent                     │
                       └───────────────┬───────────┬────────────┘
                          transfer     │           │  transfer
                                       ▼           ▼
                        ┌────────────────────┐ ┌────────────────────┐
                        │ diagnosis_agent     │ │ dealer_agent        │
                        │  tool: ask_taki     │ │  tool: find_dealers │
                        └─────────┬───────────┘ └─────────┬──────────┘
                                  │  MCP (Bearer identity token)       │
                                  ▼                                    ▼
                        ┌──────────────────────────────────────────────┐
                        │ taki-mcp  (private)                          │
                        │  ask_taki → GPU model + runtime dose guard   │
                        │  find_dealers → verified sellers (DB only)   │
                        └──────────────────────────────────────────────┘
```

## Agents

| Agent | Model | Tool(s) via MCP | Job |
|---|---|---|---|
| `taki_root` | Gemini | — (routes) | Reads the farmer's message, transfers to a specialist. |
| `diagnosis_agent` | Gemini | `ask_taki`, `taki_info` | Pest/disease symptoms, crop timing, general practice. |
| `dealer_agent` | Gemini | `find_dealers` | Where to buy — verified sellers only, never invented. |

Each sub-agent's MCP toolset is `tool_filter`-scoped, so it can only see the
tools it should use.

## Why Gemini reasons, not the self-hosted Gemma

Routing between tools needs reliable function-calling. Gemma-4B (the TAKI model)
is weak at that, so it stays the *advisory voice* — reached through `ask_taki`,
where the dose rules apply — while a capable model does the orchestration.
Vertex is already enabled on the project and uses ADC, so no API key is needed.

Switch the brain with `AGENT_MODEL` in `.env` (e.g. a LiteLLM id pointing at the
self-hosted Gemma) if you want to keep reasoning in-house — expect weaker
routing.

## Run it

```bash
make agent-smoke   # routing + tools end-to-end, prints which agent/tool handled each prompt
make agent-web     # ADK dev UI at http://127.0.0.1:8000 — pick 'taki_root' and chat
make agent-deploy  # private, CPU-only Cloud Run service
```

Needs `TAKI_MCP_URL` in `.env`, Vertex ADC (`gcloud auth application-default
login`), and a gcloud identity token for the private MCP server.

## Known limitations (Week-1 demo)

- **Identity token is captured once** at toolset construction (ADK fixes the
  connection headers). Google ID tokens last ~1h — fine for `adk web`/`adk run`
  and this demo. A long-lived production service should wrap the transport to
  refresh the token per call.
- **Reasoning goes to Gemini**, i.e. farmer text leaves the self-hosted
  boundary. Acceptable for the demo; revisit for privacy if needed.
- Answer quality in Hausa is bounded by the underlying Gemma model (see
  `MODELS.md`).

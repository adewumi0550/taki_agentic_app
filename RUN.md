# Running TAKI after a restart

`gcloud` is on your PATH only in interactive zsh (via `~/.zshrc`), so open a
normal Terminal tab and `cd` here first:

```bash
cd ~/Desktop/taki
```

## See it working — the deployed farmer UI (recommended)

The chat UI is a **private** Cloud Run service. This command opens it on
`localhost:8081` using your own Google login, so no one else can reach it:

```bash
make start
```

Then open http://localhost:8081 in your browser. Ask a question in Hausa or
English. Leave the command running; press Ctrl-C to close the tunnel.
First message after idle is slow (~90s) — the GPU is waking from zero.

> Needs you to be logged in: `gcloud auth login` (once). If `gcloud` is “command
> not found”, run `exec zsh` first to reload your shell PATH.

## Run the whole thing on your laptop instead (no Cloud Run web/MCP)

Runs the MCP server and the web UI locally; they still call the **deployed**
GPU model. Free except for GPU wake on each question:

```bash
make run-local
```

Open http://localhost:8080.

## Just the model, one question

```bash
make local                       # local Ollama (no cloud, no GPU bill)
make smoke                       # hit the Cloud Run model, prove 403 lockdown
```

## Command map

| Command | What it does | GPU $ |
|---|---|---|
| `make start` | Open the deployed farmer UI at localhost:8081 | on each question |
| `make run-local` | MCP + web on your laptop → deployed model | on each question |
| `make web-smoke` | health + one chat + 403 check against taki-web | yes |
| `make mcp-smoke` | MCP client test against taki-mcp + 403 check | yes |
| `make local` | Gemma answering in Hausa, fully local | no |
| `make deploy` / `make mcp-deploy` / `make web-deploy` / `make agent-deploy` | (re)deploy each service | build only |
| `make agent-web` | ADK dev UI for the multi-agent system at :8000 | on each question |
| `make agent-smoke` | multi-agent routing + tools end-to-end | on each question |

All three Cloud Run services (`taki`, `taki-mcp`, `taki-web`) are private and
scale to zero. Idle cost is image storage only.

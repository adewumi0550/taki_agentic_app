# TAKI — Week 3

TAKI is an agrochemical advisory agent for smallholder farmers in northern
Nigeria, answering in Hausa and English.

By Week 3 the stack is four tiers: the model plane (Gemma, local + private
Cloud Run GPU), an MCP server that guards and logs every answer, a farmer chat
UI, and an ADK multi-agent tier on top. The original model-plane commands still
work from a clean checkout with only `.env` filled in:

```bash
make local     # Gemma answering a Hausa prompt on this machine, via Ollama
make deploy    # the same model serving from a private Cloud Run URL
make smoke     # hit that URL, print the reply, prove it is locked down
```

Higher tiers: `make mcp-*`, `make web-*`, `make agent-*` (see below).

---

## The one thing to understand

`taki_model/src/client.py` talks to **both** backends. Local Ollama and the
private Cloud Run service both speak the OpenAI `/v1/chat/completions` wire
format, so the difference between them is exactly two values:

| | `base_url` | `api_key` |
|---|---|---|
| **local** | `http://localhost:11434/v1` | ignored by Ollama |
| **cloudrun** | `$TAKI_BASE_URL` | `gcloud auth print-identity-token` |

Same SDK, same request, same model ID, same parsing. Look at the `BACKENDS`
dict in `client.py` — that dict is the whole story. No request ever reaches
OpenAI; the OpenAI SDK is used purely as a protocol client.

---

## Layout

```
taki/
  README.md
  MODELS.md                       verified model IDs, dates, source links
  Makefile                        local / deploy / smoke / evals / guard / clean
  .env.example                    every variable, documented
  .gitignore
  taki_model/
    Modelfile                     base model + TAKI system prompt (templated)
    render_modelfile.py           ONE renderer, used by local build and image build
    build.sh                      builds the `taki` model on this machine
    requirements.txt
    config/models.yaml            single source of truth for model IDs
    src/client.py                 one client, two backends
    src/prompts/hausa_intent.md   the system prompt
    evals/prompts.jsonl           20 Hausa agronomy prompts
    evals/run_evals.py            runs them against either backend, or both
    serving/Dockerfile            bakes the model into the image
    serving/deploy.sh             idempotent private Cloud Run GPU deploy
    serving/smoke_test.sh         cold/warm timing + the 403 check
    scripts/check_no_doses.sh     fails the build if a dose appears anywhere
  taki_mcp/                       MCP server: ask_taki, find_dealers, + dose guard, logging
  taki_web/                       farmer chat UI (MCP client)
  taki_agent/                     ADK multi-agent tier (Gemini reasons, MCP acts)
```

## Agent tier (taki_agent)

A Google ADK multi-agent system on top of the MCP server: a root router
delegates to a `diagnosis_agent` (uses the `ask_taki` tool) and a
`dealer_agent` (uses `find_dealers`). The agents reason with Gemini (Vertex AI)
and act only through MCP, so the dose guard and conversation log apply to
everything they do. See [taki_agent/README.md](taki_agent/README.md).

```bash
make agent-smoke   # routing + tools end-to-end
make agent-web     # ADK dev UI at http://127.0.0.1:8000
make agent-deploy  # private Cloud Run service
```

---

## No model string is hardcoded

Every model ID comes from `taki_model/config/models.yaml`. `client.py`,
`build.sh`, `deploy.sh`, `smoke_test.sh` and the Dockerfile all read it from
there. Changing one line in that file changes the local model, the container
image and the eval runs together.

The Dockerfile receives the IDs through a generated `build.env` rather than
Docker `ARG`s, because `gcloud builds submit --tag` provides no way to pass
`--build-arg` — ARGs would silently arrive empty.

---

## Safety: no doses in this repo. Ever.

TAKI must never state an application rate, a mixing ratio, a pre-harvest
interval or a re-entry interval. Rates are legally registered per country, per
crop and per product, and they are revised. A rate recalled by a language model
has no provenance and no expiry. Getting it wrong underdoses the crop,
overdoses the soil, or sends someone into a treated field too early.

Where a rate would belong, the repo and the model both use the placeholder
`<DOSE_FROM_REGISTRY>`, and the answer points the farmer at the product label
and their local registry.

This is enforced mechanically, not by good intentions:

```bash
make guard
```

`taki_model/scripts/check_no_doses.sh` scans every git-tracked file and exits
non-zero if it finds a number bound to `ml/L`, `g/L`, `kg/ha`, a pre-harvest
phrasing, or a re-entry interval. `make model` and `make deploy` both run it
first, so a dose cannot reach an image.

One eval prompt (`practice-04`) asks for a dose and a mixing ratio outright.
That is deliberate — it is the adversarial check that the system prompt holds.

---

## Environment variables

Copy `.env.example` to `.env` and fill it in. `.env` is gitignored.

| Variable | Used by | Default | What it does |
|---|---|---|---|
| `TAKI_BACKEND` | client, evals | `local` | Which backend to talk to: `local` or `cloudrun`. |
| `TAKI_BASE_URL` | client, evals, smoke | *(empty)* | Cloud Run service URL **with `/v1` appended**. Required for the `cloudrun` backend. `make deploy` prints the value to paste here. |
| `GCP_PROJECT_ID` | deploy, smoke | — | Google Cloud project. Required. |
| `GCP_REGION` | deploy, smoke | `us-central1` | Must be a region that supports your `GPU_TYPE`. `deploy.sh` validates this before spending anything. |
| `CLOUD_RUN_SERVICE` | deploy, smoke | `taki` | Service name. Re-running `deploy.sh` with the same name **updates** the service rather than creating a second one. |
| `AR_REPO` | deploy | `taki` | Artifact Registry repo for the serving image. Created if absent. |
| `GPU_TYPE` | deploy | `nvidia-l4` | `nvidia-l4` or `nvidia-rtx-pro-6000`. |
| `CPU` | deploy | `8` | vCPU. L4 needs at least 4; 8 is Google's recommendation. |
| `MEMORY` | deploy | `32Gi` | L4 needs at least 16Gi; 32Gi is Google's recommendation. |
| `MAX_INSTANCES` | deploy | `1` | **Hard ceiling on how many GPUs can bill at once.** Raise only deliberately. |
| `CONCURRENCY` | deploy | `4` | Requests per instance; also sets `OLLAMA_NUM_PARALLEL`. |
| `HF_TOKEN` | *(unused by default)* | *(empty)* | Not needed. Ollama-library pulls are unauthenticated. Only relevant if you switch to fetching weights from Hugging Face, whose Gemma repos are gated. See MODELS.md section 2. |

---

## Which commands cost money

| Command | GPU charges? | Notes |
|---|---|---|
| `make local` | **No** | Runs entirely on this machine. |
| `make evals` | **No** | Free by default (`BACKEND=local`). |
| `make guard` | **No** | Text scan. |
| `make clean` | **No** | Does not touch Cloud Run. |
| `make deploy` | **YES** | Cloud Build minutes, Artifact Registry storage, and a GPU-backed Cloud Run service. |
| `make smoke` | **YES** | Wakes a GPU instance from zero and sends two requests. |
| `make evals BACKEND=cloudrun` | **YES** | 20 requests against the GPU service. |
| `make evals BACKEND=both` | **YES** | Same, plus the free local run. |

The service is deployed with GPU **scale-to-zero**, which Cloud Run supports
(verified — see MODELS.md section 3). Idle costs nothing but image storage.
`MAX_INSTANCES=1` caps concurrent GPU billing.

To stop all Cloud Run charges completely:

```bash
gcloud run services delete taki --region us-central1
```

---

## Running it

### 1. Local

```bash
make local
```

Creates a venv, pulls the base model if absent, builds the `taki` Ollama model
from `Modelfile` + the Hausa system prompt, and asks it a Hausa question.

To ask something else:

```bash
make local HAUSA_PROMPT="Yaushe zan shuka gero?"
```

Or drive the client directly:

```bash
.venv/bin/python taki_model/src/client.py --backend local --prompt "Sannu, mene ne wannan kwaro?"
```

### 2. Deploy — costs money

```bash
make deploy
```

Idempotent. Creates the Artifact Registry repo if missing, renders the
Modelfile, builds the image with Cloud Build (the weights are pulled on
Google's network, not yours), and deploys with `--no-allow-unauthenticated`.
Its **last line is the service URL**. Put that URL plus `/v1` into `.env` as
`TAKI_BASE_URL`.

If GPU quota is missing, it says so in plain language and gives you the exact
console link and metric name to request an increase.

### 3. Smoke — costs money

```bash
make smoke
```

Three checks:

1. an authenticated chat completion, with the reply printed
2. cold-start latency and warm latency, timed and reported separately
3. **the negative test** — the identical request with no `Authorization`
   header, which must be rejected. Anything other than 403/401 fails the
   script loudly, because an open GPU endpoint is an open bill.

Measured on 2026-09-05 (L4, `us-central1`): cold call **95.2s**, warm call
**6.5s**, unauthenticated **403**. The cold number is scale-from-zero with a
3.3GB model in the image — see MODELS.md section 6.

### 4. Evals

```bash
make evals                    # local, free
make evals BACKEND=cloudrun   # costs money
make evals BACKEND=both       # side-by-side comparison
```

20 Hausa agronomy prompts across pest symptoms, crop timing and general
practice. Prints latency, token counts and output; with `both`, prints the two
backends side by side. Full results land in `.eval_out/`.

There is no scoring harness, deliberately. **Hausa quality is unverified** —
Hausa is not named in the Gemma model card language lists (MODELS.md section
4). These prompts exist so a human can look at real output and decide, rather
than assume.

---

## Before you trust any of this

Read [MODELS.md](MODELS.md). It records what was verified on 2026-09-05, with
source links — Gemma tags, Cloud Run GPU flags and regions, minimum machine
shapes, scale-to-zero, and whether a Hugging Face token is needed. It also
records the two things that could **not** be verified: this project's GPU quota
limit, and Hausa output quality.

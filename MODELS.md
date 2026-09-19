# MODELS.md — verified facts

Everything below was checked on **2026-09-05**. Model tags and Cloud Run GPU
flags move; re-check before trusting this file in a later week. Anything that
could **not** be verified is marked **UNVERIFIED** rather than guessed.

Local toolchain at time of checking: `ollama 0.32.5`, `gcloud 559.0.0`,
`docker 29.6.1`, `python 3.14.3`.

---

## 1. Ollama model tags

Checked against the live Ollama library page, not from memory.

### gemma3 — source: <https://ollama.com/library/gemma3>

| Tag | Download size | Context | Modality |
|---|---|---|---|
| `gemma3:270m` | 292MB | 32K | text |
| `gemma3:1b` | 815MB | 32K | text |
| `gemma3:4b` | 3.3GB | 128K | text, image |
| `gemma3:12b` | 8.1GB | 128K | text, image |
| `gemma3:27b` | 17GB | 128K | text, image |

`gemma3:latest` resolves to `gemma3:4b`. Quantization-aware variants exist with
an `-it-qat` suffix (e.g. `gemma3:1b-it-qat`), roughly 3x smaller memory
footprint at comparable quality.

### gemma4 — source: <https://ollama.com/library/gemma4>

| Tag | Download size | Context | Modality |
|---|---|---|---|
| `gemma4:e2b` | 7.2GB | 128K | text, image |
| `gemma4:e4b` | 9.6GB | 128K | text, image |
| `gemma4:12b` | 7.6GB | 256K | text, image |
| `gemma4:26b` | 19GB | 256K | text, image |
| `gemma4:31b` | 20GB | 256K | text, image |

`gemma4:latest` resolves to `gemma4:e4b`. This machine already had
`gemma4:latest` (9.6GB) pulled before this session started.

### What TAKI uses

`taki_model/config/models.yaml` sets **`gemma3:4b`** as the single model ID for *both*
backends. Reasons, in order:

1. 3.3GB is under the 10GB threshold at which Google still recommends baking
   weights into the container image (see §3), so cold start stays reasonable.
2. It fits an L4 (24GB VRAM) with headroom, so we can use the cheap GPU shape
   rather than the RTX PRO 6000 shape the Google tutorial defaults to.
3. 128K context is far more than an advisory turn needs.

`gemma3:12b` and `gemma4:e4b` are listed as alternatives in
`taki_model/config/models.yaml`; both still fit one L4. Changing one line there changes
local and Cloud Run together.

---

## 2. Does this need a Hugging Face token?

**No — not on the path this repo takes.** Verified two ways:

- Pulling `gemma3:4b` from the **Ollama library** requires no account and no
  token. The pull ran in this session with no credentials configured.
- Pulling the same weights from **Hugging Face** *does* require a token. The
  canonical repo <https://huggingface.co/google/gemma-3-4b-it> states it "is
  publicly accessible, but you have to accept the conditions to access its
  files and content" — i.e. a gated repo needing a logged-in account and an
  access token.

So `HF_TOKEN` is present in `.env.example` but is left blank and is unused by
the default path. It only matters if you switch the Dockerfile to fetch weights
from Hugging Face instead of from Ollama.

---

## 3. Cloud Run GPU

Source: <https://docs.cloud.google.com/run/docs/configuring/services/gpu>
Best practices: <https://docs.cloud.google.com/run/docs/configuring/services/gpu-best-practices>
Worked example: <https://docs.cloud.google.com/run/docs/tutorials/gpu-gemma-with-ollama>

### Flags

GPU is attached with `--gpu 1` plus:

- `--gpu-type nvidia-l4` or `--gpu-type nvidia-rtx-pro-6000`
- `--no-gpu-zonal-redundancy` (or `--gpu-zonal-redundancy`)

Zonal redundancy is **optional**, not required. It is a
price/reliability tradeoff. This repo defaults to `--no-gpu-zonal-redundancy`
because it is the cheaper option and a Week-3 advisory prototype does not need
zonal failover.

### Supported regions

| GPU | Regions |
|---|---|
| `nvidia-l4` | asia-southeast1, asia-south1, europe-west1, europe-west4, us-central1, us-east4 |
| `nvidia-rtx-pro-6000` | asia-southeast1, asia-south2, europe-west4, us-central1 |

`GCP_REGION` defaults to `us-central1`, which supports both.

### Minimum machine shape

| GPU | Minimum | Recommended |
|---|---|---|
| `nvidia-l4` | 4 CPU / 16Gi | 8 CPU / 32Gi |
| `nvidia-rtx-pro-6000` | 20 CPU / 80Gi | — |

`.env.example` defaults to the L4 recommended shape: `CPU=8`, `MEMORY=32Gi`.

### Scale to zero

**Yes — confirmed supported.** The docs state that a Cloud Run service
configured with a GPU "can scale down to zero for cost savings when not in
use." This is why `make smoke` times a cold call and a warm call separately:
the first request after idle pays the scale-from-zero cost.

### Weights: in the image, or downloaded at start?

Google's best-practices page recommends downloading from Cloud Storage for
large models, and says container-image storage is "best suited for smaller
models less than 10 GB", noting such models "benefit from Cloud Run's
optimized container streaming infrastructure."

`gemma3:4b` is 3.3GB, so this repo **bakes the model into the image**. This
deliberately diverges from the Google tutorial, which uses the stock
`ollama/ollama` image and pulls the model at container start with
`--args="-c,(sleep 15 && ollama pull MODEL) & ollama serve"`. Pulling at start
means every cold start re-downloads the model and needs a 240-second startup
probe. Baking it in trades a slower build for a much faster, more predictable
cold start.

### Quota

Docs: new projects get initial quota automatically — 3 GPUs for L4, 3,000
milliGPU for RTX PRO 6000 — and a quota increase must be requested beyond that.

**UNVERIFIED for this project.** The quota *metrics* exist on
`steadfast-helix-429321-b2`:

```
run.googleapis.com/nvidia_l4_gpu_allocation
run.googleapis.com/nvidia_l4_gpu_allocation_no_zonal_redundancy
run.googleapis.com/nvidia_rtx_pro_6000_gpu_allocation
run.googleapis.com/nvidia_rtx_pro_6000_gpu_allocation_no_zonal_redundancy
```

but `gcloud alpha services quota list` returned `quotaBuckets: null` for all of
them, so the actual limit for this project could not be read before deploying.
Rather than guess, `taki_model/serving/deploy.sh` detects a quota rejection at deploy time
and prints the exact console URL to request an increase.

---

## 4. Hausa support — read this before trusting output

This is the weakest verified point in the stack and should not be glossed over.

- The Gemma 3 model card says its training data "includes content in over 140
  languages". Gemma 4 is documented as pre-trained on 140+ languages with
  out-of-the-box support for 35+.
  Source: <https://ai.google.dev/gemma/docs/core/model_card_4>
- **Hausa is not named** in the language lists on either the Gemma 3 HF model
  card or the Gemma 4 material checked on this date.

So: Hausa is plausibly inside the 140+ pre-training set but is **not** in the
35+ explicitly supported set, and no published per-language benchmark for Hausa
was found on this date. **Treat Hausa fluency as UNVERIFIED until measured.**
That is precisely what `taki_model/evals/prompts.jsonl` exists for — 20 Hausa agronomy
prompts run side by side against both backends so quality is observed rather
than assumed. If Hausa output is poor, the fix is a fine-tune or a different
base model, and that decision belongs to a later week.

---

## 5. Environment notes for this machine

- **Deploying account: `saheedadewumi32@gmail.com`.** This project has four
  credentialed accounts (`adewumiadewale493@gmail.com`, `cloudusecase@gmail.com`,
  `saheed@proofa.tech`, `saheedadewumi32@gmail.com`); `saheedadewumi32@gmail.com`
  is the ACTIVE one and it matches `gcloud config core/account`. There is no
  mismatch. `deploy.sh` prints the active account as its first line so the
  credential in use is never a guess.

- Project `steadfast-helix-429321-b2` already has `run.googleapis.com`,
  `artifactregistry.googleapis.com` and `cloudbuild.googleapis.com` enabled, so
  no API enablement step is needed.
- Local network measured ~1.3 MB/s during the `gemma3:4b` pull, so the local
  pull takes a while. The Cloud Build pull for the image runs on Google's
  network and is much faster.

---

## 6. Measured on the first real deploy — 2026-09-05

These are observations from this project, not documentation claims.

**Service:** `taki`, revision `taki-00002-xrc`, `us-central1`,
1x `nvidia-l4`, 8 vCPU / 32Gi, `--no-gpu-zonal-redundancy`,
`--max-instances 1`, `--no-allow-unauthenticated`.

| Measurement | Value |
|---|---|
| GPU quota | **Available.** The deploy succeeded without a quota request, so the default L4 allocation covered `--max-instances 1`. The docs' "3 L4 GPUs for new projects" held here. |
| Generation speed on L4 | **~72 tokens/s** (from the container's own `print_timing` logs) |
| Cold call (scale from zero) | **95.2s** |
| Warm call | **6.5s** |
| Unauthenticated request | **HTTP 403** — service is private |
| Cloud Build time (3.3GB pull + bake + push) | **~6m20s** |
| Re-check 2026-09-12, same revision, 7 days idle | cold **100.3s**, warm **2.2s**, unauthenticated **403** |

Note the cold start: ~95s is the honest number for scale-from-zero with a
3.3GB model baked into the image. Budget for it, or keep a minimum instance
warm — which costs money continuously and is why this repo does not.

### Three bugs worth remembering

1. **`gcloud builds submit --tag` cannot pass `--build-arg`.** Docker `ARG`s in
   the Dockerfile arrived empty and the build died on `ollama pull ""`. Model
   IDs now reach the image through a generated `build.env` file instead.

2. **Uncapped generation is expensive.** The first deployed revision had no
   `num_predict`. On one request the model generated 3431 tokens until it hit
   the 4096 context ceiling (`truncated = 1`) — 47 seconds of GPU time for a
   single farmer question. `PARAMETER num_predict 400` in the Modelfile cut the
   warm call from 48s to 6.5s. On a GPU service, an unbounded reply length is a
   cost bug, not just a UX one.

3. **"python3" is not one thing on a Mac.** The shell scripts defaulted to
   `python3`, which was Homebrew's 3.14 (with pyyaml) in one shell and Apple's
   `/usr/bin/python3` (without it) in the next. The model ID came back empty
   and the smoke test sent `"model": ""` to the GPU and got a 400. The
   Makefile now passes the venv interpreter to every script as `$PY`, and each
   script refuses to continue if the model ID resolves empty. Found
   2026-09-12 on a fresh shell — exactly the "clean checkout" case.

### 20-prompt eval on Cloud Run — 2026-09-12

`make evals BACKEND=cloudrun`, warm instance, revision `taki-00002-xrc`.

| | |
|---|---|
| Completed | 20 / 20, no errors |
| Latency | median **2.49s**, mean **3.07s** |
| Tokens | 14,530 prompt (system prompt is ~720 of every request), 2,937 completion |
| Numeric dose / ratio in any output | **none** |
| Adversarial dose request (`practice-04`) | refused with `<DOSE_FROM_REGISTRY>`, label + dealer referral |
| `<pest>` placeholder leak | 0 |
| Hit the 400-token cap | 3 (`pest-09`, `timing-01`, `timing-05`) — each ~6s; the cap is doing its job |

Two things the eval surfaced that the smoke test could not:

- **The placeholder is over-applied.** 12 of 20 replies contain
  `<DOSE_FROM_REGISTRY>`, including crop-timing and soil questions where no
  chemical was mentioned. The model has learned "TAKI answers end with the
  registry sentence" rather than "use it when a rate would go here". A
  prompt-engineering task for Week 2, not a safety problem — an unnecessary
  placeholder is harmless, a missing one is not.
- **Hausa is weak across the board**, consistent with section 4. Replies are
  on-topic and recognisably Hausa but frequently garbled, with English
  loanwords (`scan`, `Aphid`) and occasional restating of the question. The
  full text is in `.eval_out/results-cloudrun.json`; read a few before
  deciding whether a 4B base is viable for farmer-facing Hausa.

### Hausa quality — first observation

Confirming section 4: output is **grammatically weak**. It is recognisably
Hausa and on-topic, but phrasing is often garbled and some sentences do not
parse. The safety constraint held under direct attack — asked outright for a
dose and a mixing ratio, the model returned `<DOSE_FROM_REGISTRY>` and referred
the farmer to the product label, with no number in any unit.

An early version of the system prompt caused the model to parrot the literal
meta-placeholder `<pest>` from its example. Fixed by naming a concrete pest in
the example and stating that only `<DOSE_FROM_REGISTRY>` may be reproduced
verbatim. Worth remembering: a model this size copies examples literally.

---

## 7. Re-check list

When revisiting this file, re-verify in this order — these are the items most
likely to have changed:

1. Gemma tag names and sizes on ollama.com.
2. Cloud Run GPU region list and whether new GPU types were added.
3. Whether minimum CPU/memory for a GPU shape changed.
4. Whether Hausa has been named explicitly in a Gemma model card.

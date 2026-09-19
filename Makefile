# TAKI — Week 1 model plane.
#
#   make local   — Gemma answering a Hausa prompt on this machine via Ollama
#   make deploy  — the same model serving from a private Cloud Run URL   [$ GPU]
#   make smoke   — hit that URL, print the reply, prove it is locked down [$ GPU]
#
# Targets marked [$ GPU] provision or wake a Cloud Run GPU instance and cost
# real money. Everything else is free and local. See README.md.

SHELL := /bin/bash
.DEFAULT_GOAL := help

PKG  := taki_model
VENV := .venv
# Absolute, and deliberately NOT named PY: the `export` below exports every
# make variable, and the serving scripts honour $PY as an override. A
# repo-root-relative path would break once they cd into taki_model/.
VENV_PY := $(CURDIR)/$(VENV)/bin/python

# .env is optional for the local path and required for deploy/smoke.
ifneq (,$(wildcard .env))
include .env
export
endif

# A real farmer question, in Hausa: "My maize leaves are yellowing from the
# bottom up. What is happening?" Deliberately a nutrition/pest ambiguity, so a
# weak model is easy to spot.
HAUSA_PROMPT ?= Sannu. Ganyen masarata na juya launin rawaya daga kasa zuwa sama. Mene ne ke faruwa, kuma me zan yi?

.PHONY: help venv guard model local deploy smoke evals clean \
        mcp-local mcp-deploy mcp-smoke web-local web-deploy web-smoke web-open \
        agent-venv agent-web agent-smoke agent-deploy

help:
	@echo "TAKI — model plane"
	@echo ""
	@echo "  make local    Build the taki model and answer a Hausa prompt locally (free)"
	@echo "  make deploy   Build the image and deploy to private Cloud Run GPU   [COSTS MONEY]"
	@echo "  make smoke    Cold+warm timing against Cloud Run, and a 403 check   [COSTS MONEY]"
	@echo "  make evals    Run the 20 Hausa prompts (BACKEND=local|cloudrun)"
	@echo "  make guard    Fail if any dose, ratio or interval is in a tracked file"
	@echo "  make clean    Remove venv, caches and the local taki model"
	@echo ""
	@echo "  make mcp-local   Run the MCP server on :8090 against the Cloud Run model (free-ish: wakes GPU on use)"
	@echo "  make mcp-deploy  Deploy taki-mcp: private, CPU only, + conversation store   [Cloud Build only]"
	@echo "  make mcp-smoke   MCP client test against taki-mcp incl. 403 check           [wakes GPU]"
	@echo "  make web-local   Run the farmer chat UI on :8080 against a local MCP (:8090)"
	@echo "  make web-deploy  Deploy taki-web: private, CPU only                          [Cloud Build only]"
	@echo "  make web-smoke   health + chat + 403 against taki-web                          [wakes GPU]"
	@echo "  make web-open    Proxy taki-web to http://localhost:8081 with your credentials"
	@echo ""
	@echo "  make agent-web    ADK dev UI for the multi-agent system on :8000   [Gemini + wakes GPU]"
	@echo "  make agent-smoke  Run the multi-agent smoke test (routing + tools)  [Gemini + wakes GPU]"
	@echo "  make agent-deploy Deploy taki-agent: private, CPU only              [Cloud Build only]"
	@echo ""
	@echo "  Model ID comes from $(PKG)/config/models.yaml — never from a literal."

# ---------------------------------------------------------------------------
# environment
# ---------------------------------------------------------------------------

$(VENV)/.installed: $(PKG)/requirements.txt
	@echo "==> creating venv (system python is externally managed)"
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --quiet --upgrade pip
	$(VENV)/bin/pip install --quiet -r $(PKG)/requirements.txt
	@touch $@
	@echo "==> venv ready"

venv: $(VENV)/.installed

# ---------------------------------------------------------------------------
# safety
# ---------------------------------------------------------------------------

guard:
	@./$(PKG)/scripts/check_no_doses.sh

# ---------------------------------------------------------------------------
# local path — free
# ---------------------------------------------------------------------------

# The shell scripts read config/models.yaml through $PY. It must be the venv
# interpreter: system python3 may be Apple's, which has no pyyaml.
model: guard venv
	@PY=$(VENV_PY) ./$(PKG)/build.sh

local: venv model
	@echo ""
	@echo "==> asking TAKI, in Hausa, on the local Ollama backend"
	@echo ""
	@$(VENV_PY) $(PKG)/src/client.py --backend local --prompt "$(HAUSA_PROMPT)"

# ---------------------------------------------------------------------------
# Cloud Run path — THESE COST MONEY
# ---------------------------------------------------------------------------

deploy: guard venv
	@echo "==> deploying to Cloud Run WITH A GPU. This is billable."
	@PY=$(VENV_PY) ./$(PKG)/serving/deploy.sh

smoke: venv
	@echo "==> smoke test will wake a GPU instance. This is billable."
	@PY=$(VENV_PY) ./$(PKG)/serving/smoke_test.sh

# ---------------------------------------------------------------------------
# evals
# ---------------------------------------------------------------------------

BACKEND ?= local

evals: venv
	@$(VENV_PY) $(PKG)/evals/run_evals.py --backend $(BACKEND)

# ---------------------------------------------------------------------------
# clean
# ---------------------------------------------------------------------------

clean:
	@echo "==> removing venv and caches"
	rm -rf $(VENV) .eval_out
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "==> removing the local taki model (base weights are kept)"
	-ollama rm $$($(VENV_PY) -c "import yaml;print(yaml.safe_load(open('$(PKG)/config/models.yaml'))['taki_model']['name'])" 2>/dev/null || echo taki) 2>/dev/null || true
	@echo "==> clean. Cloud Run service is untouched — delete it with:"
	@echo "    gcloud run services delete $${CLOUD_RUN_SERVICE:-taki} --region $${GCP_REGION:-us-central1}"

# ---------------------------------------------------------------------------
# taki_mcp — MCP server (model call + runtime dose guard + conversation store)
# ---------------------------------------------------------------------------

MODEL_ID_CMD = $(VENV_PY) -c "import yaml;print(yaml.safe_load(open('$(PKG)/config/models.yaml'))['taki_model']['name'])"
MCP_REQS = taki_mcp/requirements.txt taki_web/requirements.txt

$(VENV)/.installed-mcp: $(MCP_REQS) $(VENV)/.installed
	$(VENV)/bin/pip install --quiet -r taki_mcp/requirements.txt -r taki_web/requirements.txt
	@touch $@

mcp-local: $(VENV)/.installed-mcp
	@echo "==> MCP server on http://127.0.0.1:8090/mcp  (model: Cloud Run, store: disabled unless TAKI_DB_DSN set)"
	@TAKI_MODEL_ID=$$($(MODEL_ID_CMD)) PORT=8090 TAKI_ENV=local-dev $(VENV_PY) taki_mcp/server.py

mcp-deploy: guard $(VENV)/.installed-mcp
	@PY=$(VENV_PY) ./taki_mcp/deploy.sh

mcp-smoke: $(VENV)/.installed-mcp
	@$(VENV_PY) taki_mcp/smoke_test.py $${TAKI_MCP_URL:?set TAKI_MCP_URL in .env (make mcp-deploy prints it)}

# ---------------------------------------------------------------------------
# taki_web — farmer chat UI (MCP client; no model logic)
# ---------------------------------------------------------------------------

web-local: $(VENV)/.installed-mcp
	@echo "==> farmer UI on http://127.0.0.1:8080  (talking to MCP at $${TAKI_MCP_LOCAL:-http://127.0.0.1:8090})"
	@TAKI_MCP_URL=$${TAKI_MCP_LOCAL:-http://127.0.0.1:8090} PORT=8080 $(VENV_PY) taki_web/app.py

web-deploy: guard $(VENV)/.installed-mcp
	@./taki_web/deploy.sh

web-smoke:
	@./taki_web/smoke_test.sh

start: web-open   ## alias: open the DEPLOYED farmer UI in your browser

run-local: $(VENV)/.installed-mcp  ## run the FULL stack locally (MCP :8090 + web :8080)
	@echo "==> starting MCP (:8090) and web (:8080). Ctrl-C stops both."
	@TAKI_MODEL_ID=$$($(MODEL_ID_CMD)) PORT=8090 TAKI_ENV=local-dev $(VENV_PY) taki_mcp/server.py & \
	  MCP_PID=$$!; sleep 3; \
	  TAKI_MCP_URL=http://127.0.0.1:8090 PORT=8080 $(VENV_PY) taki_web/app.py; \
	  kill $$MCP_PID 2>/dev/null || true

web-open:
	@echo "==> http://localhost:8081  (Ctrl-C to stop the proxy)"
	@gcloud run services proxy $${WEB_SERVICE:-taki-web} --region $${GCP_REGION:-us-central1} --project $${GCP_PROJECT_ID} --port 8081

# ---------------------------------------------------------------------------
# taki_agent — ADK multi-agent tier (reasons with Gemini, acts via MCP)
# Uses its OWN python 3.13 venv: ADK's dependency chain does not support 3.14.
# ---------------------------------------------------------------------------

AGENT_VENV := .venv-agent
AGENT_PY   := $(CURDIR)/$(AGENT_VENV)/bin/python
AGENT_ADK  := $(CURDIR)/$(AGENT_VENV)/bin/adk
PY313      := $(shell command -v python3.13 || echo python3)

$(AGENT_VENV)/.installed: taki_agent/requirements.txt
	@echo "==> creating agent venv on $(PY313) (ADK needs python < 3.14)"
	$(PY313) -m venv $(AGENT_VENV)
	$(AGENT_VENV)/bin/pip install --quiet --upgrade pip
	$(AGENT_VENV)/bin/pip install --quiet -r taki_agent/requirements.txt 'mcp>=1.24,<2'
	@touch $@

agent-venv: $(AGENT_VENV)/.installed

# ADK discovers taki_agent/ from the repo root. Requires TAKI_MCP_URL in .env.
agent-web: agent-venv
	@echo "==> ADK dev UI at http://127.0.0.1:8000  (pick 'taki_root')"
	@set -a; [ -f .env ] && . ./.env; set +a; \
	  GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_PROJECT=$${GCP_PROJECT_ID} \
	  GOOGLE_CLOUD_LOCATION=$${GCP_REGION:-us-central1} \
	  $(AGENT_ADK) web --host 127.0.0.1 --port 8000 .

agent-smoke: agent-venv
	@set -a; [ -f .env ] && . ./.env; set +a; \
	  GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_PROJECT=$${GCP_PROJECT_ID} \
	  GOOGLE_CLOUD_LOCATION=$${GCP_REGION:-us-central1} \
	  $(AGENT_PY) -m taki_agent.smoke_test

agent-deploy: agent-venv
	@./taki_agent/deploy.sh

"""
TAKI — one client, two backends.

The entire point of this file is that the difference between Gemma running on
your laptop and Gemma running on a private Cloud Run GPU is exactly TWO VALUES:

    base_url   — where to send the request
    api_key    — what goes in the Authorization header

Everything else — the SDK, the request shape, the response parsing, the model
ID — is identical. Both backends speak the OpenAI /v1/chat/completions wire
format: Ollama exposes it natively, and on Cloud Run we run the same Ollama
behind an IAM-authenticated URL. So we use the OpenAI SDK as a *protocol
client*. No request ever reaches OpenAI.

Look at BACKENDS below. That dict is the whole story.

No model string is hardcoded here. Model IDs come from config/models.yaml.

Usage:
    python src/client.py --backend local  --prompt "Sannu, mene ne wannan kwaro?"
    python src/client.py --backend cloudrun --prompt "..."
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import yaml
from openai import OpenAI

# taki_model/src/client.py -> taki_model/
PKG_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PKG_ROOT.parent
CONFIG_PATH = PKG_ROOT / "config" / "models.yaml"


# --------------------------------------------------------------------------
# config — the single source of truth for model IDs
# --------------------------------------------------------------------------

def load_config() -> dict:
    """Read config/models.yaml. Nothing in this repo may hardcode a model ID."""
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_dotenv() -> None:
    """Minimal .env reader so a clean checkout needs no extra dependency.

    Real environment variables always win over the file, so you can override
    any single value inline without editing .env.
    """
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# --------------------------------------------------------------------------
# the two backends — this is the part that matters
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Backend:
    name: str
    base_url: str
    api_key: str
    note: str


def _identity_token() -> str:
    """Google-signed identity token for calling a private Cloud Run service.

    The service is deployed --no-allow-unauthenticated, so an unauthenticated
    request gets a 403. smoke_test.sh proves that.
    """
    try:
        return subprocess.run(
            ["gcloud", "auth", "print-identity-token"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except FileNotFoundError:
        sys.exit("gcloud not found on PATH — needed for the cloudrun backend.")
    except subprocess.CalledProcessError as exc:
        sys.exit(
            "Could not mint an identity token. Run `gcloud auth login` first.\n"
            f"gcloud said: {exc.stderr.strip()}"
        )


def _local_backend(cfg: dict) -> Backend:
    # Deliberately does NOT read TAKI_BASE_URL. That variable holds the Cloud
    # Run URL, so honouring it here would silently send `make local` to the
    # billable GPU service the moment .env was filled in for a deploy.
    return Backend(
        name="local",
        base_url=os.environ.get("OLLAMA_BASE_URL") or cfg["backends"]["local"]["base_url"],
        # Ollama ignores the key entirely, but the SDK requires a non-empty
        # string. This is the ONLY place the two backends differ in auth.
        api_key="ollama-unused",
        note="Ollama on localhost — no auth, no GPU charges.",
    )


def _cloudrun_backend(cfg: dict) -> Backend:
    base_url = os.environ.get("TAKI_BASE_URL")
    if not base_url:
        sys.exit(
            "TAKI_BASE_URL is not set.\n"
            "Run `make deploy`, then put the URL it prints (with /v1 on the end) "
            "into .env as TAKI_BASE_URL."
        )
    return Backend(
        name="cloudrun",
        base_url=base_url.rstrip("/"),
        api_key=_identity_token(),
        note="Private Cloud Run GPU service — IAM authenticated, billed.",
    )


#: Two entries. Same protocol, same SDK, same request. Different URL and key.
BACKENDS = {
    "local": _local_backend,
    "cloudrun": _cloudrun_backend,
}


def resolve_backend(name: str, cfg: dict) -> Backend:
    if name not in BACKENDS:
        sys.exit(f"Unknown backend {name!r}. Choose one of: {', '.join(BACKENDS)}")
    return BACKENDS[name](cfg)


def build_client(backend: Backend) -> OpenAI:
    """One SDK, both backends. Only base_url and api_key change."""
    return OpenAI(base_url=backend.base_url, api_key=backend.api_key, timeout=600.0)


# --------------------------------------------------------------------------
# chat
# --------------------------------------------------------------------------

@dataclass
class Reply:
    text: str
    latency_s: float
    prompt_tokens: int | None
    completion_tokens: int | None
    model: str
    backend: str


def chat(prompt: str, backend_name: str = "local", model: str | None = None,
         temperature: float = 0.3) -> Reply:
    """Send one prompt. Identical code path for both backends."""
    load_dotenv()
    cfg = load_config()
    backend = resolve_backend(backend_name, cfg)

    # Model ID from config, never a literal. The Modelfile-built `taki` model
    # already carries the Hausa system prompt, so we do not resend it here.
    model = model or cfg["taki_model"]["name"]

    client = build_client(backend)

    started = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    elapsed = time.perf_counter() - started

    usage = response.usage
    return Reply(
        text=(response.choices[0].message.content or "").strip(),
        latency_s=elapsed,
        prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
        completion_tokens=getattr(usage, "completion_tokens", None) if usage else None,
        model=model,
        backend=backend.name,
    )


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="TAKI — one client, two backends.")
    parser.add_argument("--backend", default=os.environ.get("TAKI_BACKEND", "local"),
                        choices=sorted(BACKENDS))
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--model", default=None,
                        help="Override the model ID from config/models.yaml.")
    parser.add_argument("--temperature", type=float, default=0.3)
    args = parser.parse_args()

    cfg = load_config()
    backend = resolve_backend(args.backend, cfg)
    print(f"backend  : {backend.name}  ({backend.note})")
    print(f"base_url : {backend.base_url}")
    print(f"model    : {args.model or cfg['taki_model']['name']}  (from config/models.yaml)")
    print("-" * 72)

    reply = chat(args.prompt, args.backend, args.model, args.temperature)

    print(reply.text)
    print("-" * 72)
    print(f"latency  : {reply.latency_s:.2f}s")
    print(f"tokens   : prompt={reply.prompt_tokens} completion={reply.completion_tokens}")


if __name__ == "__main__":
    main()

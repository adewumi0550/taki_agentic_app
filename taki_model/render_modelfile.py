#!/usr/bin/env python3
"""Render taki_model/Modelfile into a concrete Modelfile.

One renderer, used by both paths, so the local model and the container model
can never drift apart:

  build.sh          -> renders, then `ollama create` on this machine
  serving/deploy.sh -> renders, then bakes the result into the image

Substitutes:
  __TAKI_BASE_MODEL__   <- taki_model.base from config/models.yaml
  __TAKI_SYSTEM_PROMPT__ <- src/prompts/hausa_intent.md

Usage: render_modelfile.py OUTPUT_PATH [BASE_MODEL_OVERRIDE]
"""
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parent


def render(base_override: str | None = None) -> str:
    cfg = yaml.safe_load((PKG / "config" / "models.yaml").read_text(encoding="utf-8"))
    base = base_override or cfg["taki_model"]["base"]

    prompt = (PKG / "src" / "prompts" / "hausa_intent.md").read_text(encoding="utf-8")
    # Ollama's SYSTEM """...""" block cannot contain a bare triple quote.
    prompt = prompt.replace('"""', "'''")

    tmpl = (PKG / "Modelfile").read_text(encoding="utf-8")
    return (tmpl
            .replace("__TAKI_BASE_MODEL__", base)
            .replace("__TAKI_SYSTEM_PROMPT__", prompt))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    out = Path(sys.argv[1])
    override = sys.argv[2] if len(sys.argv) > 2 else None
    out.write_text(render(override), encoding="utf-8")
    print(f"rendered -> {out}")

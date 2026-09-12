#!/usr/bin/env bash
# Builds the `taki` Ollama model on THIS machine from taki_model/Modelfile.
#
# Base model ID and model name come from taki_model/config/models.yaml, never
# from a literal here. Rendering is delegated to render_modelfile.py, which
# serving/deploy.sh also uses — so the local model and the container model are
# built from the same template and the same system prompt.
#
# Safe to re-run: `ollama create` overwrites in place.
set -euo pipefail
cd "$(dirname "$0")"

CONFIG=config/models.yaml
PY="${PY:-python3}"

BASE=$("$PY" -c "import yaml;print(yaml.safe_load(open('$CONFIG'))['taki_model']['base'])" 2>/dev/null || true)
NAME=$("$PY" -c "import yaml;print(yaml.safe_load(open('$CONFIG'))['taki_model']['name'])" 2>/dev/null || true)
if [ -z "$BASE" ] || [ -z "$NAME" ]; then
  echo "ERROR: could not read model IDs from $CONFIG." >&2
  echo "       \$PY is '$PY' — it needs pyyaml. Run via 'make local', which uses the venv." >&2
  exit 1
fi

echo "==> base model : $BASE   (from $CONFIG)"
echo "==> taki model : $NAME"

if ! ollama list 2>/dev/null | awk 'NR>1{print $1}' | grep -qx "$BASE"; then
  echo "==> base model not present locally, pulling $BASE ..."
  ollama pull "$BASE"
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

"$PY" render_modelfile.py "$TMP/Modelfile" >/dev/null
ollama create "$NAME" -f "$TMP/Modelfile"
echo "==> built: $NAME"

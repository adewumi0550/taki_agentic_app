# TAKI MCP server. CPU only — the GPU lives in the model service.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --quiet -r requirements.txt

COPY *.py ./

# Cloud Run injects PORT. TAKI_BASE_URL / TAKI_MODEL_ID / TAKI_DB_DSN come from
# deploy.sh — no model string and no credential is baked into this image.
EXPOSE 8080
CMD ["python", "server.py"]

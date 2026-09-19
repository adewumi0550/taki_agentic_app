# TAKI agent tier (Google ADK). CPU only — it reasons with Gemini (Vertex) and
# calls the TAKI MCP server for actions. Served with ADK's built-in API server.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
# ADK needs the mcp extra for the MCP toolset.
RUN pip install --quiet -r requirements.txt 'mcp>=1.24,<2'

# The agent package must sit under a directory ADK can discover by name.
COPY . ./taki_agent/

# Vertex + MCP config arrive as env at deploy time (deploy.sh). No secrets baked.
ENV GOOGLE_GENAI_USE_VERTEXAI=TRUE
EXPOSE 8080

# ADK's FastAPI server exposes /run, /run_sse and a dev UI for the discovered
# agent(s). --host 0.0.0.0 and Cloud Run's $PORT.
CMD ["sh", "-c", "adk api_server --host 0.0.0.0 --port ${PORT:-8080} ."]

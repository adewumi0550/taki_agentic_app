"""Build an ADK McpToolset pointed at the private TAKI MCP server.

The MCP server is deployed --no-allow-unauthenticated, so every call needs a
Google identity token whose audience is the MCP service origin. We mint one and
pass it as a Bearer header on the streamable-HTTP connection.

Token caveat (demo): ADK fixes the connection headers at construction time, so
the token here is captured once. Google identity tokens last ~1h, which is fine
for `adk web`/`adk run` sessions and this demo. A long-lived production service
should wrap the transport to refresh the token; noted in the README.

`tool_filter` lets each sub-agent see only the MCP tools it should use.
"""
from __future__ import annotations

import subprocess
import sys

import httpx
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams


def _identity_token(audience: str) -> str:
    # On Cloud Run, prefer the metadata server (this service's own SA);
    # locally, fall back to the developer's gcloud identity token.
    meta = (
        "http://metadata.google.internal/computeMetadata/v1/instance/"
        "service-accounts/default/identity"
    )
    try:
        r = httpx.get(meta, params={"audience": audience, "format": "full"},
                      headers={"Metadata-Flavor": "Google"}, timeout=2.0)
        if r.status_code == 200 and r.text.strip():
            return r.text.strip()
    except httpx.HTTPError:
        pass
    try:
        out = subprocess.run(["gcloud", "auth", "print-identity-token"],
                             capture_output=True, text=True, check=True, timeout=30)
        if out.stdout.strip():
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass
    sys.exit("Could not mint an identity token for the MCP server. Run `gcloud auth login`.")


def make_toolset(mcp_url: str, tool_filter: list[str] | None = None) -> MCPToolset:
    audience = mcp_url.removesuffix("/mcp")
    token = _identity_token(audience)
    return MCPToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=mcp_url,
            headers={"Authorization": f"Bearer {token}"},
            # The first ask_taki wakes the MCP instance AND the GPU model behind
            # it (scale-from-zero ~90s). The 5s default session timeout makes the
            # agent think the tool is missing and loop, so widen both.
            timeout=60,
            sse_read_timeout=300,
        ),
        tool_filter=tool_filter,
    )

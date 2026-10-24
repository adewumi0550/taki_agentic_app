"""The wire between the two projects.

MCP_URL points at underwriting-mcp. Every toolset is scoped with
tool_filter, so an agent cannot see a tool it has no business calling --
not "is told not to call", cannot see.
"""
import os
from urllib.parse import urlparse

from google.adk.tools.mcp_tool import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StreamableHTTPConnectionParams,
)

MCP_URL = os.environ.get("MCP_URL", "http://127.0.0.1:8080/mcp")

_LOCAL = {"127.0.0.1", "localhost", "::1"}


def _headers() -> dict:
    """A bearer identity token for the private Cloud Run service.

    NOTE: tokens last ~1h. Captured once here, which is fine for a demo;
    a long-lived service must refresh per call.
    """
    if (urlparse(MCP_URL).hostname or "") in _LOCAL:
        return {}
    import google.auth.transport.requests
    import google.oauth2.id_token

    audience = MCP_URL.rsplit("/mcp", 1)[0]
    token = google.oauth2.id_token.fetch_id_token(
        google.auth.transport.requests.Request(), audience
    )
    return {"Authorization": f"Bearer {token}"}


def scoped_toolset(tool: str) -> MCPToolset:
    return MCPToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=MCP_URL, headers=_headers()
        ),
        tool_filter=[tool],
    )

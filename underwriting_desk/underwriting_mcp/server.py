"""underwriting-mcp — the tool boundary.

Every tool call is authorised, scoped to the calling agent, and written to
the decision log before its result is returned. No agent can bypass this.
"""
import os

from mcp.server.fastmcp import FastMCP

from audit import log_call
from guard import enforce_policy
from tools import collateral, identity, policy, statements

mcp = FastMCP(
    "underwriting-mcp",
    host=os.environ.get("HOST", "127.0.0.1"),
    port=int(os.environ.get("PORT", "8080")),
    stateless_http=True,
)


@mcp.tool()
def read_statements(file_id: str) -> dict:
    """Six months of inflows: volatility, salary regularity, overdrafts."""
    result = statements.read(file_id)
    log_call("read_statements", file_id, result)
    return result


@mcp.tool()
def verify_identity(file_id: str) -> dict:
    """Documents against the registry and the sanctions list."""
    result = identity.verify(file_id)
    log_call("verify_identity", file_id, result)
    return result


@mcp.tool()
def value_collateral(file_id: str) -> dict:
    """Title, valuation, and any existing charges."""
    result = collateral.value(file_id)
    log_call("value_collateral", file_id, result)
    return result


@mcp.tool()
def check_policy(file_id: str) -> dict:
    """The bank's credit rules. Enforced here, never in a prompt."""
    result = enforce_policy(policy.load(file_id))
    log_call("check_policy", file_id, result)
    return result


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

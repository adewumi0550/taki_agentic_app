"""The four specialists. One factory, one tool each."""
import os

from google.adk.agents import LlmAgent

from mcp_toolset import scoped_toolset

AGENT_MODEL = os.environ.get("AGENT_MODEL", "gemini-2.5-flash")

_RULES = (
    "\n\nYou MUST call your tool first, exactly once, passing the file_id "
    "from the message. Never answer before the tool returns. "
    "Report only what the tool returned. Cite the `source` field it gives "
    "you on every finding. If something is outside your domain, say "
    "'not my domain' rather than guessing. Be brief: at most four lines."
)

BRIEFS = {
    "statements_agent": (
        "You read bank statements. Report inflow volatility, salary "
        "regularity, overdraft days, and the debt service coverage ratio "
        "(dscr). State plainly whether this applicant can service the debt."
    ),
    "identity_agent": (
        "You verify identity documents against the registry and the "
        "sanctions list. Report matches, mismatches and sanctions hits."
    ),
    "collateral_agent": (
        "You assess collateral: title, valuation, existing charges. State "
        "whether the security is real, unpledged, and what it is worth."
    ),
    "policy_agent": (
        "You check the file against the bank's credit rules. Report every "
        "breach the check_policy tool returns, by name. Do not reinterpret "
        "or soften them."
    ),
}

TOOLS = {
    "statements_agent": "read_statements",
    "identity_agent": "verify_identity",
    "collateral_agent": "value_collateral",
    "policy_agent": "check_policy",
}


def specialist(name: str) -> LlmAgent:
    return LlmAgent(
        name=name,
        model=AGENT_MODEL,
        instruction=BRIEFS[name] + _RULES,
        output_key=name,
        tools=[scoped_toolset(TOOLS[name])],
        # a fan-out specialist answers; it never hands off to a peer
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


def all_specialists() -> list[LlmAgent]:
    return [specialist(n) for n in BRIEFS]

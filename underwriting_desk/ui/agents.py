"""The money desk: four specialists, fanned out, then a reconciler.

Same shape as the loan desk -- one tool each via tool_filter, no peer
transfer, ParallelAgent inside a SequentialAgent.
"""
import os

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.mcp_tool import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StreamableHTTPConnectionParams,
)

MCP_URL = os.environ.get("MONEY_MCP_URL", "http://127.0.0.1:8787/mcp")
MODEL = os.environ.get("AGENT_MODEL", "gemini-2.5-flash")

_RULES = (
    "\n\nCall your tool first, exactly once, with the budget_id from the "
    "message. Never answer before it returns. Then write ONE short "
    "paragraph -- at most 40 words -- speaking directly to the person, in "
    "plain English, quoting whatever figures the tool returned (naira "
    "amounts where it gave them, percentages otherwise). Never remark on "
    "figures the tool did not return. "
    "Amounts are Nigerian naira; write them like NGN 45,000. No bullet "
    "points, no headings, no preamble."
)

SPECS = {
    "budget_agent": (
        "You look at what housing and food take out of someone's income. "
        "Say whether rent is inside the common 30% guide and what that "
        "means month to month.",
        "read_budget",
    ),
    "savings_agent": (
        "You look at the buffer. Say what they are putting aside, how that "
        "compares to the 20% rule of thumb, and how long it takes them to "
        "build one month of cover.",
        "check_savings",
    ),
    "policy_agent": (
        "You compare the split against published planning benchmarks. "
        "Report every breach the tool returns, by name and number. Do not "
        "soften them. If there are none, say so plainly.",
        "check_benchmarks",
    ),
    "risk_agent": (
        "You are the lender's eye. Say what monthly repayment a bank would "
        "work with on this income, and whether this split could carry it.",
        "loan_capacity",
    ),
}


def _toolset(tool: str) -> MCPToolset:
    return MCPToolset(
        connection_params=StreamableHTTPConnectionParams(url=MCP_URL),
        tool_filter=[tool],
    )


def specialist(name: str) -> LlmAgent:
    brief, tool = SPECS[name]
    return LlmAgent(
        name=name,
        model=MODEL,
        instruction=brief + _RULES,
        output_key=name,
        tools=[_toolset(tool)],
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


RECONCILE = """
You close out a household money review. You have four independent
findings below.

Rules, in order:
1. PRECEDENCE. A benchmark breach outranks a comfortable number. A thin
   savings buffer is not cured by cheap rent.
2. EVIDENCE. Name the figures the specialists actually reported.
3. NAME THE TENSION. If two findings pull in opposite directions, say so
   out loud rather than averaging them.

Write at most three sentences, speaking directly to the person, warm but
straight. End with the single most useful thing they could change this
month. This is general guidance against published rules of thumb, not
regulated financial advice.
"""


def _reconcile_instruction(ctx: ReadonlyContext) -> str:
    parts = []
    for name in SPECS:
        v = ctx.state.get(name)
        parts.append(f"### {name}\n{v}" if v else f"### {name}\n(did not report)")
    return RECONCILE + "\n\nFINDINGS:\n\n" + "\n\n".join(parts)


def build_money_desk() -> SequentialAgent:
    evidence = ParallelAgent(
        name="evidence", sub_agents=[specialist(n) for n in SPECS]
    )
    closer = LlmAgent(
        name="reconciler", model=MODEL,
        instruction=_reconcile_instruction, output_key="memo",
    )
    return SequentialAgent(name="money_desk", sub_agents=[evidence, closer])


root_agent = build_money_desk()

"""TAKI multi-agent system (Google ADK).

A root router delegates each farmer message to a specialist sub-agent. The
agents REASON with Gemini; they ACT only through the TAKI MCP server, so the
dose guard and conversation log in taki-mcp still sit on every model answer —
the agent tier cannot bypass them.

    root_agent (taki_root) ── routes to ──┬─ diagnosis_agent  ── ask_taki
                                          └─ dealer_agent     ── find_dealers

ADK discovers `root_agent` in this module (via taki_agent/__init__.py). Run it
with `adk web`, `adk run taki_agent`, or the Runner in smoke_test.py.
"""
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools import google_search
from google.adk.tools.agent_tool import AgentTool

from .dose_guard import after_model_dose_guard

from .config import load
from .mcp_toolset import make_toolset

_cfg = load()

# One MCP toolset per specialist, each filtered to just the tools it may use.
_diagnosis_tools = make_toolset(_cfg.mcp_url, tool_filter=["ask_taki", "taki_info"])
_dealer_tools = make_toolset(_cfg.mcp_url, tool_filter=["find_dealers"])

# google_search is a built-in tool and cannot be mixed with other tools in one
# agent, so it lives alone here and is exposed to the dealer agent as a tool.
web_search_agent = LlmAgent(
    model=_cfg.model,
    name="web_search",
    description="Searches the public web for agro-input / pesticide sellers.",
    instruction=(
        "Search the web for agricultural-input or agrochemical sellers "
        "(agro-dealers, farm-input shops) near the location asked about. Report "
        "only shop name, town/area and a contact if clearly shown. Do NOT report "
        "any product prices, doses, mixing ratios or application instructions "
        "from the pages you read. If you find nothing credible, say so."
    ),
    tools=[google_search],
)

diagnosis_agent = LlmAgent(
    model=_cfg.model,
    name="diagnosis_agent",
    description=(
        "Answers farming questions — pest and disease symptoms, crop timing, "
        "and general practice — by consulting TAKI. Use for anything about what "
        "is wrong with a crop or how/when to grow it."
    ),
    instruction=(
        "You handle farming advice for a smallholder in northern Nigeria.\n"
        "ALWAYS get the answer by calling the `ask_taki` tool with the farmer's "
        "question, in the farmer's own words and language (Hausa or English). "
        "Do not answer from your own knowledge — TAKI is the source of record "
        "and it carries the dose-safety rules.\n"
        "Return TAKI's reply faithfully. If it contains the token "
        "<DOSE_FROM_REGISTRY>, KEEP it exactly and never replace it with a "
        "number — pesticide amounts come only from the product label and the "
        "registry, never from you.\n"
        "Reply ONLY in Hausa or English — whichever the farmer used. Never use "
        "any other language."
    ),
    tools=[_diagnosis_tools],
    after_model_callback=after_model_dose_guard,
)

dealer_agent = LlmAgent(
    model=_cfg.model,
    name="dealer_agent",
    description=(
        "Finds agro-input / pesticide sellers near a location. Use when the "
        "farmer asks where to buy a product or find a dealer/agro-shop."
    ),
    instruction=(
        "The farmer wants to know where to buy an agro-input. Work in TWO steps "
        "and be clear about which source each seller comes from:\n"
        "1. FIRST call `find_dealers` with the location (town, LGA or state) and, "
        "if the farmer named a product type, the product_class. Sellers it "
        "returns are VERIFIED — present these first and label them as verified.\n"
        "2. ONLY if `find_dealers` returns none, call the `web_search` tool to "
        "look for agro-dealers near that location. Present anything it finds as "
        "UNVERIFIED web results the farmer must confirm before trusting, and "
        "ALWAYS also tell them to check with their local agricultural extension "
        "officer.\n"
        "NEVER invent a shop, address or phone number — only report what a tool "
        "returned. NEVER include any product dose, price-as-advice, mixing ratio "
        "or application instruction, even if a web page shows one.\n"
        "Reply ONLY in Hausa or English — whichever the farmer used. Never use "
        "any other language."
    ),
    tools=[_dealer_tools, AgentTool(agent=web_search_agent)],
    after_model_callback=after_model_dose_guard,
)

root_agent = LlmAgent(
    model=_cfg.model,
    name="taki_root",
    description="TAKI — routes a smallholder farmer's request to the right specialist.",
    instruction=(
        "You are TAKI, an agricultural advisor for smallholder farmers in "
        "northern Nigeria. Read the farmer's message and delegate:\n"
        "- Symptoms, diseases, pests, crop timing, or general farming practice "
        "-> transfer to `diagnosis_agent`.\n"
        "- Where to buy a product / find a seller or agro-dealer "
        "-> transfer to `dealer_agent`.\n"
        "If a message needs both (e.g. 'what is this and where do I buy "
        "treatment'), handle the diagnosis first, then the dealer lookup.\n"
        "Never give a pesticide dose, mixing ratio, or waiting period yourself. "
        "Always work ONLY in Hausa or English — match the farmer's language and "
        "never reply in any other language."
    ),
    sub_agents=[diagnosis_agent, dealer_agent],
)

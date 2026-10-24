"""money-desk MCP server — the tool boundary for the budget desk.

Same shape as underwriting_mcp: four tools, rules enforced here, every
call logged before its result returns. Tools take a budget_id and read it
from budgets/, exactly as the loan tools take a file_id.
"""
import json
import os
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parent
# Cloud Run's image is read-only apart from /tmp, so both are env-driven.
BUDGETS = Path(os.environ.get("BUDGET_DIR", ROOT.parent / "budgets"))
LOG = Path(os.environ.get("LOG_DIR", ROOT.parent)) / "money_log.jsonl"
BUDGETS.mkdir(parents=True, exist_ok=True)

# Published planning rules of thumb, not the policy of any named bank.
BENCH = {"rent": 30, "feeding": 35, "savings": 20, "school": 25, "debt_service": 33}
SOURCE = "planning benchmarks: 50/30/20, housing <=30%, repayments <=33%"

mcp = FastMCP(
    "money-desk-mcp",
    host=os.environ.get("MCP_HOST", "127.0.0.1"),
    port=int(os.environ.get("MCP_PORT", "8787")),
    stateless_http=True,
)


def _load(budget_id: str) -> dict:
    p = BUDGETS / f"{budget_id}.json"
    if not p.exists():
        raise ValueError(f"no such budget: {budget_id}")
    return json.loads(p.read_text())


def _log(tool: str, budget_id: str, result: dict) -> None:
    LOG.open("a").write(
        json.dumps({"ts": time.time(), "tool": tool, "budget_id": budget_id,
                    "result": result}) + "\n"
    )


def _money(b: dict, key: str) -> int:
    return round(b["income"] * b["alloc"][key] / 100)


@mcp.tool()
def read_budget(budget_id: str) -> dict:
    """Housing and feeding load: what share of income each takes."""
    b = _load(budget_id)
    a = b["alloc"]
    r = {
        "income_monthly": b["income"],
        "rent_pct": a["rent"], "rent_amount": _money(b, "rent"),
        "feeding_pct": a["feeding"], "feeding_amount": _money(b, "feeding"),
        "school_pct": a["school"], "school_amount": _money(b, "school"),
        "rent_limit": BENCH["rent"], "feeding_limit": BENCH["feeding"],
        "source": SOURCE,
    }
    _log("read_budget", budget_id, r)
    return r


@mcp.tool()
def check_savings(budget_id: str) -> dict:
    """The buffer: savings rate, amount, and months to one month of cover."""
    b = _load(budget_id)
    pct = b["alloc"]["savings"]
    r = {
        "savings_pct": pct, "savings_amount": _money(b, "savings"),
        "target_pct": BENCH["savings"],
        "months_to_one_month_cover": round(100 / pct, 1) if pct else None,
        "meets_target": pct >= BENCH["savings"],
        "source": SOURCE,
    }
    _log("check_savings", budget_id, r)
    return r


@mcp.tool()
def check_benchmarks(budget_id: str) -> dict:
    """The rules. Enforced here, never in a prompt."""
    b = _load(budget_id)
    a = b["alloc"]
    breaches = []
    if a["rent"] > BENCH["rent"]:
        breaches.append(f"housing {a['rent']}% over {BENCH['rent']}%")
    if a["feeding"] > BENCH["feeding"]:
        breaches.append(f"feeding {a['feeding']}% over {BENCH['feeding']}%")
    if a["savings"] < BENCH["savings"]:
        breaches.append(f"savings {a['savings']}% under {BENCH['savings']}%")
    if a["school"] > BENCH["school"]:
        breaches.append(f"school fees {a['school']}% over {BENCH['school']}%")
    r = {"breaches": breaches, "passed": not breaches,
         "benchmarks": BENCH, "source": SOURCE}
    _log("check_benchmarks", budget_id, r)
    return r


@mcp.tool()
def loan_capacity(budget_id: str) -> dict:
    """What a lender would work with, on the common repayment rule."""
    b = _load(budget_id)
    a = b["alloc"]
    capacity = round(b["income"] * BENCH["debt_service"] / 100)
    lendable = a["savings"] >= 10 and a["rent"] <= BENCH["rent"]
    r = {
        "monthly_income": b["income"],
        "debt_service_cap_pct": BENCH["debt_service"],
        "monthly_capacity": capacity,
        "buffer_pct": a["savings"], "housing_pct": a["rent"],
        "would_lend": lendable,
        "source": SOURCE,
    }
    _log("loan_capacity", budget_id, r)
    return r


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

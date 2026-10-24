"""Credit rules, enforced in the server.

A rule that lives in a prompt lives nowhere enforceable. These run on
every call, whatever the agent was persuaded to ask for.
"""
MAX_EXPOSURE = 50_000_000
EXCLUDED_SECTORS = {"crypto_trading", "unlicensed_lending"}
MIN_DSCR = 1.25

POLICY_VERSION = "credit_policy_v4"


def enforce_policy(facts: dict) -> dict:
    breaches = []
    if facts.get("exposure", 0) > MAX_EXPOSURE:
        breaches.append(
            f"exposure_limit: {facts['exposure']:,} exceeds {MAX_EXPOSURE:,}"
        )
    if facts.get("sector") in EXCLUDED_SECTORS:
        breaches.append(f"excluded_sector: {facts['sector']}")
    if facts.get("dscr", 0) < MIN_DSCR:
        breaches.append(
            f"dscr_below_minimum: {facts.get('dscr')} is under {MIN_DSCR}"
        )
    return {
        "breaches": breaches,
        "passed": not breaches,
        "facts": facts,
        "source": facts.get("source", POLICY_VERSION),
    }

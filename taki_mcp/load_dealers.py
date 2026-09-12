#!/usr/bin/env python3
"""Load real dealer rows into taki_dealers from a CSV you control.

    python taki_mcp/load_dealers.py path/to/dealers.csv

CSV columns (header required): name, location, state, phone, products, verified, note
  * products: '|'-separated list, e.g. "insecticide|herbicide"  (may be empty)
  * verified: true/false — ONLY true rows are ever surfaced by find_dealers,
    so load unverified rows freely and flip them to true once checked.

Reads TAKI_DB_DSN from the environment (or .env). Refuses to run with no DSN.
This inserts human-provided data; it never generates dealers.
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import psycopg
from dealers import DealerStore, SCHEMA


def _load_dotenv() -> None:
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main(path: str) -> int:
    _load_dotenv()
    dsn = os.environ.get("TAKI_DB_DSN", "").strip()
    if not dsn:
        sys.exit("TAKI_DB_DSN is not set — cannot load dealers without a database.")

    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
    if not rows:
        sys.exit(f"{path} has no data rows.")

    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(SCHEMA)
        n = 0
        for r in rows:
            products = [p.strip() for p in (r.get("products") or "").split("|") if p.strip()]
            verified = str(r.get("verified", "")).strip().lower() in ("1", "true", "yes", "y")
            c.execute(
                """INSERT INTO taki_dealers (name, location, state, phone, products, verified, note)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (r["name"].strip(), r["location"].strip(), (r.get("state") or "").strip() or None,
                 (r.get("phone") or "").strip() or None, products, verified,
                 (r.get("note") or "").strip() or None),
            )
            n += 1
    print(f"loaded {n} dealer row(s) from {path}")
    print(f"status: {DealerStore(dsn).ensure_schema()}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    raise SystemExit(main(sys.argv[1]))

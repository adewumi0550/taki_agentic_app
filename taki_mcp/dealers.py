"""Dealer directory — real, verified pesticide/agro sellers, from the DB only.

This is the seller-side twin of the dose rule. TAKI must never invent a shop
any more than it invents a rate: a wrong dealer sends a farmer to a stockist
that does not exist, or worse, launders a fake product. So this store returns
ONLY rows a human has marked `verified = true` in the database. No data loaded
=> empty result => the caller says "I don't have sellers for that area", never
a guess.

Same Postgres database as the conversation store (Cloud SQL: proofa-agent-db /
agent_db), reached through TAKI_DB_DSN. If the DSN is empty the directory is
simply empty and every lookup returns nothing.

Load real data with taki_mcp/load_dealers.py from a CSV you control.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

log = logging.getLogger("taki.dealers")

SCHEMA = """
CREATE TABLE IF NOT EXISTS taki_dealers (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT        NOT NULL,
    location    TEXT        NOT NULL,          -- town / LGA, free text
    state       TEXT,                           -- e.g. Kano, Kaduna
    phone       TEXT,
    products    TEXT[],                         -- product classes stocked, optional
    verified    BOOLEAN     NOT NULL DEFAULT false,  -- only verified rows are ever returned
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS taki_dealers_location_idx ON taki_dealers (lower(location));
CREATE INDEX IF NOT EXISTS taki_dealers_state_idx    ON taki_dealers (lower(state));
"""


@dataclass
class DealerStore:
    dsn: str

    @property
    def enabled(self) -> bool:
        return bool(self.dsn)

    def _conn(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn, connect_timeout=10, autocommit=True)

    def ensure_schema(self) -> str:
        if not self.enabled:
            return "disabled (TAKI_DB_DSN not set)"
        try:
            with self._conn() as c:
                c.execute(SCHEMA)
                n = c.execute("SELECT count(*) FROM taki_dealers WHERE verified").fetchone()[0]
                total = c.execute("SELECT count(*) FROM taki_dealers").fetchone()[0]
            return f"ok ({n} verified of {total} loaded)"
        except psycopg.Error as exc:
            log.error("dealer store unavailable: %s", exc)
            return f"ERROR: {exc}".splitlines()[0]

    def find(self, location: str, product_class: str | None = None,
             limit: int = 10) -> list[dict[str, Any]]:
        """Verified dealers whose location OR state matches `location`.

        Returns [] when the store is disabled, empty, or nothing matches.
        Never fabricates a row.
        """
        if not self.enabled:
            return []
        location = (location or "").strip()
        if not location:
            return []
        like = f"%{location.lower()}%"
        params: list[Any] = [like, like]
        product_sql = ""
        if product_class and product_class.strip():
            product_sql = "AND %s = ANY (products)"
            params.append(product_class.strip())
        params.append(max(1, min(limit, 50)))
        try:
            with self._conn() as c:
                cur = c.cursor(row_factory=dict_row)
                cur.execute(
                    f"""
                    SELECT name, location, state, phone, products, note
                    FROM taki_dealers
                    WHERE verified
                      AND (lower(location) LIKE %s OR lower(coalesce(state,'')) LIKE %s)
                      {product_sql}
                    ORDER BY name
                    LIMIT %s
                    """,
                    params,
                )
                return cur.fetchall()
        except psycopg.Error as exc:
            log.error("dealer lookup failed: %s", exc)
            return []

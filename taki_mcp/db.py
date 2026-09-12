"""Conversation store on Postgres (Cloud SQL: proofa-agent-db / agent_db).

Every question and reply that passes through the MCP server is written here
with timing, token counts and both guard flags. That gives an audit trail for
the dose rule: `dose_guard_triggered = true` rows are the ones where the model
tried to emit a rate and was stopped.

Connection: TAKI_DB_DSN. On Cloud Run the DSN points at the Cloud SQL unix
socket that --add-cloudsql-instances mounts:
  postgresql://USER:PASS@/agent_db?host=/cloudsql/PROJECT:REGION:INSTANCE
Locally, run the Cloud SQL Auth Proxy and use host=127.0.0.1.

If the DSN is empty the store is disabled and every call is a no-op that
returns None. The server still answers — logging must never take TAKI down —
but `taki_info` reports the store as disabled so it cannot go unnoticed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

log = logging.getLogger("taki.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS taki_conversations (
    id                        BIGSERIAL PRIMARY KEY,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    channel                   TEXT        NOT NULL,           -- 'mcp' | 'web' | ...
    farmer_id                 TEXT,                            -- opaque caller id, optional
    question                  TEXT        NOT NULL,
    reply                     TEXT        NOT NULL,            -- what the caller received (post-guard)
    model_id                  TEXT        NOT NULL,
    model_url                 TEXT        NOT NULL,
    latency_ms                INTEGER     NOT NULL,
    prompt_tokens             INTEGER,
    completion_tokens         INTEGER,
    used_registry_placeholder BOOLEAN     NOT NULL,            -- reply contains <DOSE_FROM_REGISTRY>
    dose_guard_triggered      BOOLEAN     NOT NULL,            -- runtime guard redacted something
    dose_guard_matches        TEXT[],                          -- what it redacted (for review)
    env_name                  TEXT        NOT NULL
);
CREATE INDEX IF NOT EXISTS taki_conversations_created_at_idx
    ON taki_conversations (created_at DESC);
CREATE INDEX IF NOT EXISTS taki_conversations_guard_idx
    ON taki_conversations (dose_guard_triggered) WHERE dose_guard_triggered;
"""


@dataclass
class Store:
    dsn: str

    @property
    def enabled(self) -> bool:
        return bool(self.dsn)

    def _conn(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn, connect_timeout=10, autocommit=True)

    def ensure_schema(self) -> str:
        """Create the table if missing. Returns a status string for taki_info."""
        if not self.enabled:
            return "disabled (TAKI_DB_DSN not set)"
        try:
            with self._conn() as c:
                c.execute(SCHEMA)
                c.execute("SELECT count(*) FROM taki_conversations")
                n = c.execute("SELECT count(*) FROM taki_conversations").fetchone()[0]
            return f"ok ({n} conversations stored)"
        except psycopg.Error as exc:
            log.error("conversation store unavailable: %s", exc)
            return f"ERROR: {exc}".splitlines()[0]

    def insert(self, row: dict[str, Any]) -> int | None:
        if not self.enabled:
            return None
        try:
            with self._conn() as c:
                cur = c.execute(
                    """
                    INSERT INTO taki_conversations
                        (channel, farmer_id, question, reply, model_id, model_url,
                         latency_ms, prompt_tokens, completion_tokens,
                         used_registry_placeholder, dose_guard_triggered,
                         dose_guard_matches, env_name)
                    VALUES (%(channel)s, %(farmer_id)s, %(question)s, %(reply)s,
                            %(model_id)s, %(model_url)s, %(latency_ms)s,
                            %(prompt_tokens)s, %(completion_tokens)s,
                            %(used_registry_placeholder)s, %(dose_guard_triggered)s,
                            %(dose_guard_matches)s, %(env_name)s)
                    RETURNING id
                    """,
                    row,
                )
                return cur.fetchone()[0]
        except psycopg.Error as exc:
            # Logging must never take the advisory path down.
            log.error("failed to store conversation: %s", exc)
            return None

    def recent(self, limit: int = 10, only_guard_hits: bool = False) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        where = "WHERE dose_guard_triggered" if only_guard_hits else ""
        try:
            with self._conn() as c:
                cur = c.cursor(row_factory=dict_row)
                cur.execute(
                    f"""
                    SELECT id, created_at, channel, farmer_id, question, reply,
                           latency_ms, prompt_tokens, completion_tokens,
                           used_registry_placeholder, dose_guard_triggered
                    FROM taki_conversations {where}
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    (max(1, min(limit, 100)),),
                )
                rows = cur.fetchall()
            for r in rows:
                if isinstance(r.get("created_at"), datetime):
                    r["created_at"] = r["created_at"].isoformat()
            return rows
        except psycopg.Error as exc:
            log.error("failed to read conversations: %s", exc)
            return []

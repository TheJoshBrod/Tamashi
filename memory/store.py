"""SQLite backing store for memory facts.

Jac library mode is in-memory only (no cross-restart persistence).
This module provides durable storage: every fact written to the Jac graph
is also written here. On startup or on cache miss, facts are reloaded from
SQLite back into the Jac graph.

Table lives in sessions.db alongside the messages table.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from core.config import settings


class FactStore:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or settings.db_path
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        con = sqlite3.connect(self._db_path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _init_db(self) -> None:
        with self._conn() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS memory_facts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     TEXT    NOT NULL,
                    content     TEXT    NOT NULL,
                    topic       TEXT    NOT NULL DEFAULT 'other',
                    source_msg_id INTEGER,
                    node_jid    TEXT,
                    created_at  TEXT    DEFAULT (datetime('now'))
                )
            """)
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_facts_user ON memory_facts(user_id)"
            )

    def insert(self, user_id: str, facts: list[dict], jids: list[str]) -> None:
        """Persist a batch of facts and their Jac node IDs."""
        with self._conn() as con:
            for fact, jid in zip(facts, jids):
                con.execute(
                    "INSERT INTO memory_facts (user_id, content, topic, source_msg_id, node_jid) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, fact["content"], fact["topic"],
                     fact.get("source_msg_id"), jid),
                )

    def get_facts(self, user_id: str, limit: int = 1000) -> list[dict]:
        """Return facts for a user, most recent first."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT content, topic, node_jid FROM memory_facts "
                "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [{"content": r["content"], "topic": r["topic"], "jid": r["node_jid"]}
                for r in rows]

    def has_user(self, user_id: str) -> bool:
        with self._conn() as con:
            row = con.execute(
                "SELECT 1 FROM memory_facts WHERE user_id = ? LIMIT 1", (user_id,)
            ).fetchone()
        return row is not None

    def list_users(self) -> list[str]:
        """Return all user_ids that have stored facts. Used by the nightly linker."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT DISTINCT user_id FROM memory_facts"
            ).fetchall()
        return [r["user_id"] for r in rows]

    def delete_user(self, user_id: str) -> None:
        """Remove all facts for a user (used in tests and /forget command)."""
        with self._conn() as con:
            con.execute("DELETE FROM memory_facts WHERE user_id = ?", (user_id,))


# Module-level singleton — same lifetime as the process.
fact_store = FactStore()

"""SQLite backing store for entity-centric memory subjects and relations.

Jac library mode is in-memory only (no cross-restart persistence).
This module provides durable storage: every Subject and Relates edge written
to the Jac graph is also written here. On startup or on cache miss, subjects
(including their recent_events WAL) are reloaded from SQLite back into the
Jac graph.

Tables live in sessions.db alongside the messages table.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from core.config import settings


class SubjectStore:
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
            # Drop legacy fact table from old architecture
            con.execute("DROP TABLE IF EXISTS memory_facts")

            con.execute("""
                CREATE TABLE IF NOT EXISTS memory_subjects (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id      TEXT    NOT NULL,
                    name         TEXT    NOT NULL,
                    summary      TEXT    NOT NULL DEFAULT '',
                    description  TEXT    NOT NULL DEFAULT '',
                    subject_type TEXT    NOT NULL DEFAULT 'other',
                    recent_events TEXT   NOT NULL DEFAULT '[]',
                    node_jid     TEXT,
                    created_at   TEXT    DEFAULT (datetime('now')),
                    updated_at   TEXT    DEFAULT (datetime('now'))
                )
            """)
            con.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_subjects_user_name
                ON memory_subjects(user_id, name)
            """)

            con.execute("""
                CREATE TABLE IF NOT EXISTS memory_relations (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    TEXT    NOT NULL,
                    src_name   TEXT    NOT NULL,
                    kind       TEXT    NOT NULL,
                    tgt_name   TEXT    NOT NULL,
                    weight     REAL    DEFAULT 1.0,
                    created_at TEXT    DEFAULT (datetime('now')),
                    updated_at TEXT    DEFAULT (datetime('now'))
                )
            """)
            con.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_relations_triple
                ON memory_relations(user_id, src_name, kind, tgt_name)
            """)

            # Authoritative per-event WAL. Replaces the JSON recent_events column
            # as the source of truth consumed by the rewriter. Each append gets a
            # stable autoincrement id so the rewriter can snapshot [ids it saw],
            # spend 10s in the LLM, then atomically delete EXACTLY those ids —
            # any new append during the LLM call gets a new id and survives the
            # delete. The JSON recent_events column remains as a derived cache,
            # kept in sync by the ingest/rewrite paths.
            con.execute("""
                CREATE TABLE IF NOT EXISTS subject_events (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id      TEXT    NOT NULL,
                    subject_name TEXT    NOT NULL,
                    payload      TEXT    NOT NULL,
                    created_at   TEXT    DEFAULT (datetime('now'))
                )
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_subject_events_user_name
                ON subject_events(user_id, subject_name)
            """)

            self._migrate_recent_events_to_subject_events(con)

    def _migrate_recent_events_to_subject_events(self, con) -> None:
        """One-time, idempotent: copy JSON recent_events into the subject_events table.

        Per-(user_id, subject_name) guard: skip any subject that already has rows
        in subject_events, so re-running this on already-migrated databases is a
        no-op. Runs inside the caller's transaction.
        """
        existing = con.execute(
            "SELECT DISTINCT user_id, subject_name FROM subject_events"
        ).fetchall()
        migrated_keys = {(r["user_id"], r["subject_name"]) for r in existing}

        rows = con.execute(
            "SELECT user_id, name, recent_events, created_at FROM memory_subjects"
        ).fetchall()
        for r in rows:
            key = (r["user_id"], r["name"])
            if key in migrated_keys:
                continue
            try:
                events = json.loads(r["recent_events"] or "[]")
            except (TypeError, ValueError):
                events = []
            if not events:
                continue
            created_at = r["created_at"] or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for event in events:
                payload = event if isinstance(event, str) else json.dumps(event)
                con.execute(
                    """
                    INSERT INTO subject_events (user_id, subject_name, payload, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (r["user_id"], r["name"], payload, created_at),
                )

    # --- Subjects ---

    @staticmethod
    def _row_to_subject(r) -> dict:
        return {
            "name": r["name"],
            "summary": r["summary"],
            "description": r["description"],
            "subject_type": r["subject_type"],
            "recent_events": json.loads(r["recent_events"]),
            "jid": r["node_jid"],
            "created_at": r["created_at"] or "",
            "updated_at": r["updated_at"] or "",
        }

    def upsert_subject(
        self,
        user_id: str,
        name: str,
        summary: str,
        description: str,
        subject_type: str,
        recent_events: list,
        node_jid: str | None = None,
    ) -> None:
        """Insert or update a subject. On conflict (user_id, name), update all fields."""
        with self._conn() as con:
            con.execute(
                """
                INSERT INTO memory_subjects
                    (user_id, name, summary, description, subject_type, recent_events, node_jid, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(user_id, name) DO UPDATE SET
                    summary       = excluded.summary,
                    description   = excluded.description,
                    subject_type  = excluded.subject_type,
                    recent_events = excluded.recent_events,
                    node_jid      = excluded.node_jid,
                    updated_at    = datetime('now')
                """,
                (user_id, name, summary, description, subject_type,
                 json.dumps(recent_events), node_jid),
            )

    def get_subjects(self, user_id: str, limit: int = 1000) -> list[dict]:
        """Return all subjects for a user, most recently updated first."""
        with self._conn() as con:
            rows = con.execute(
                """
                SELECT name, summary, description, subject_type, recent_events,
                       node_jid, created_at, updated_at
                FROM memory_subjects
                WHERE user_id = ?
                ORDER BY updated_at DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [self._row_to_subject(r) for r in rows]

    def update_subject_wal(self, user_id: str, name: str, recent_events: list) -> None:
        """Update only the recent_events WAL for an existing subject."""
        with self._conn() as con:
            con.execute(
                """
                UPDATE memory_subjects
                SET recent_events = ?, updated_at = datetime('now')
                WHERE user_id = ? AND name = ?
                """,
                (json.dumps(recent_events), user_id, name),
            )

    def get_subject_by_jid(self, user_id: str, jid: str) -> dict | None:
        """Return a single subject by node_jid, or None if not found."""
        with self._conn() as con:
            row = con.execute(
                """
                SELECT name, summary, description, subject_type, recent_events,
                       node_jid, created_at, updated_at
                FROM memory_subjects
                WHERE user_id = ? AND node_jid = ?
                """,
                (user_id, jid),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_subject(row)

    def get_subject_by_name(self, user_id: str, name: str) -> dict | None:
        """Return a single subject by name, or None if not found."""
        with self._conn() as con:
            row = con.execute(
                """
                SELECT name, summary, description, subject_type, recent_events,
                       node_jid, created_at, updated_at
                FROM memory_subjects
                WHERE user_id = ? AND name = ?
                """,
                (user_id, name),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_subject(row)

    def get_recently_active(self, user_id: str, since: datetime, limit: int = 20) -> list[dict]:
        """Return subjects updated since `since`, ordered by update time desc."""
        since_str = since.strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as con:
            rows = con.execute(
                """
                SELECT name, summary, description, subject_type, recent_events,
                       node_jid, created_at, updated_at
                FROM memory_subjects
                WHERE user_id = ? AND updated_at >= ?
                ORDER BY updated_at DESC LIMIT ?
                """,
                (user_id, since_str, limit),
            ).fetchall()
        return [self._row_to_subject(r) for r in rows]

    def has_user(self, user_id: str) -> bool:
        with self._conn() as con:
            row = con.execute(
                "SELECT 1 FROM memory_subjects WHERE user_id = ? LIMIT 1", (user_id,)
            ).fetchone()
        return row is not None

    def list_users(self) -> list[str]:
        """Return all user_ids with stored subjects."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT DISTINCT user_id FROM memory_subjects"
            ).fetchall()
        return [r["user_id"] for r in rows]

    def delete_subject(self, user_id: str, name: str) -> None:
        """Delete a subject and all relations that reference it."""
        with self._conn() as con:
            con.execute(
                "DELETE FROM memory_subjects WHERE user_id = ? AND name = ?",
                (user_id, name),
            )
            con.execute(
                "DELETE FROM memory_relations WHERE user_id = ? AND (src_name = ? OR tgt_name = ?)",
                (user_id, name, name),
            )

    def delete_relation(self, user_id: str, src_name: str, kind: str, tgt_name: str) -> None:
        """Delete a specific relation triple."""
        with self._conn() as con:
            con.execute(
                "DELETE FROM memory_relations WHERE user_id = ? AND src_name = ? AND kind = ? AND tgt_name = ?",
                (user_id, src_name, kind, tgt_name),
            )

    def delete_user(self, user_id: str) -> None:
        """Remove all subjects and relations for a user."""
        with self._conn() as con:
            con.execute("DELETE FROM memory_subjects WHERE user_id = ?", (user_id,))
            con.execute("DELETE FROM memory_relations WHERE user_id = ?", (user_id,))

    # --- Relations ---

    def upsert_relation(
        self,
        user_id: str,
        src_name: str,
        kind: str,
        tgt_name: str,
        weight: float = 1.0,
    ) -> None:
        """Insert or update a relation triple. On conflict, updates weight and updated_at."""
        with self._conn() as con:
            con.execute(
                """
                INSERT INTO memory_relations
                    (user_id, src_name, kind, tgt_name, weight)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, src_name, kind, tgt_name) DO UPDATE SET
                    weight     = excluded.weight,
                    updated_at = datetime('now')
                """,
                (user_id, src_name, kind, tgt_name, weight),
            )

    # --- Subject events WAL (authoritative per-event log) ---

    def append_event(self, user_id: str, subject_name: str, payload: str) -> int:
        """Append one event to the WAL. Returns the autoincrement id."""
        with self._conn() as con:
            cur = con.execute(
                """
                INSERT INTO subject_events (user_id, subject_name, payload)
                VALUES (?, ?, ?)
                """,
                (user_id, subject_name, payload),
            )
            return int(cur.lastrowid)

    def get_events(self, user_id: str, subject_name: str) -> list[dict]:
        """Return all pending events for a subject, oldest first, as [{id, payload}]."""
        with self._conn() as con:
            rows = con.execute(
                """
                SELECT id, payload FROM subject_events
                WHERE user_id = ? AND subject_name = ?
                ORDER BY id ASC
                """,
                (user_id, subject_name),
            ).fetchall()
        return [{"id": int(r["id"]), "payload": r["payload"]} for r in rows]

    def get_event_count(self, user_id: str, subject_name: str) -> int:
        """Return the number of pending events for a subject."""
        with self._conn() as con:
            row = con.execute(
                """
                SELECT COUNT(*) AS n FROM subject_events
                WHERE user_id = ? AND subject_name = ?
                """,
                (user_id, subject_name),
            ).fetchone()
        return int(row["n"]) if row else 0

    def delete_events_by_ids(self, ids: list[int]) -> None:
        """Atomically delete a specific set of event ids. Concurrent appends survive."""
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self._conn() as con:
            con.execute(
                f"DELETE FROM subject_events WHERE id IN ({placeholders})",
                tuple(int(i) for i in ids),
            )

    def get_relations(self, user_id: str) -> list[dict]:
        """Return all relations for a user."""
        with self._conn() as con:
            rows = con.execute(
                """
                SELECT src_name, kind, tgt_name, weight, created_at, updated_at
                FROM memory_relations WHERE user_id = ?
                """,
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]


# Module-level singleton — same lifetime as the process.
subject_store = SubjectStore()

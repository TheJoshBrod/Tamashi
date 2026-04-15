from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from core.schemas import Message, ToolCall
from sessions.base import SessionStore


class SQLiteSessionStore(SessionStore):
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS messages (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT    NOT NULL,
                    role        TEXT    NOT NULL,
                    content     TEXT,
                    tool_calls  TEXT,   -- JSON array or NULL
                    tool_call_id TEXT,
                    name        TEXT,
                    created_at  TEXT    DEFAULT (datetime('now'))
                )
            """)
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_session ON messages(session_id, id)"
            )
            con.execute("""
                CREATE TABLE IF NOT EXISTS consolidated_marks (
                    session_id     TEXT    PRIMARY KEY,
                    max_message_id INTEGER NOT NULL DEFAULT 0
                )
            """)

    def get_history(self, session_id: str, limit: int | None = None) -> list[Message]:
        with self._conn() as con:
            # Find the id of the most recent reset marker, if any
            reset_row = con.execute(
                "SELECT MAX(id) as last_id FROM messages "
                "WHERE session_id = ? AND role = 'session_reset'",
                (session_id,),
            ).fetchone()
            after_id = reset_row["last_id"] or 0

            if limit is not None:
                # Fetch the most recent `limit` messages, then re-order ascending.
                rows = con.execute(
                    "SELECT role, content, tool_calls, tool_call_id, name "
                    "FROM messages WHERE session_id = ? AND id > ? "
                    "AND role IN ('system', 'user', 'assistant', 'tool') "
                    "ORDER BY id DESC LIMIT ?",
                    (session_id, after_id, limit),
                ).fetchall()
                rows = list(reversed(rows))
            else:
                rows = con.execute(
                    "SELECT role, content, tool_calls, tool_call_id, name "
                    "FROM messages WHERE session_id = ? AND id > ? "
                    "AND role IN ('system', 'user', 'assistant', 'tool') ORDER BY id",
                    (session_id, after_id),
                ).fetchall()

        messages: list[Message] = []
        for row in rows:
            tool_calls = None
            if row["tool_calls"]:
                raw = json.loads(row["tool_calls"])
                tool_calls = [
                    ToolCall(
                        id=tc["id"],
                        name=tc["function"]["name"],
                        arguments=json.loads(tc["function"]["arguments"]),
                    )
                    for tc in raw
                ]
            messages.append(
                Message(
                    role=row["role"],
                    content=row["content"],
                    tool_calls=tool_calls,
                    tool_call_id=row["tool_call_id"],
                    name=row["name"],
                )
            )
        return messages

    def append(self, session_id: str, message: Message) -> None:
        tool_calls_json = None
        if message.tool_calls:
            tool_calls_json = json.dumps([tc.to_dict() for tc in message.tool_calls])
        with self._conn() as con:
            con.execute(
                "INSERT INTO messages (session_id, role, content, tool_calls, tool_call_id, name) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    message.role,
                    message.content,
                    tool_calls_json,
                    message.tool_call_id,
                    message.name,
                ),
            )

    def reset(self, session_id: str) -> None:
        with self._conn() as con:
            con.execute(
                "INSERT INTO messages (session_id, role) VALUES (?, 'session_reset')",
                (session_id,),
            )

    def get_max_message_id(self, session_id: str) -> int:
        """Return the highest message id for this session (post-reset).

        Counts only user/assistant turns so tool and system messages don't
        skew the consolidation-window boundary.
        """
        with self._conn() as con:
            reset_row = con.execute(
                "SELECT MAX(id) as last_id FROM messages "
                "WHERE session_id = ? AND role = 'session_reset'",
                (session_id,),
            ).fetchone()
            after_id = reset_row["last_id"] or 0
            row = con.execute(
                "SELECT MAX(id) as max_id FROM messages "
                "WHERE session_id = ? AND id > ? "
                "AND role IN ('user', 'assistant')",
                (session_id, after_id),
            ).fetchone()
        return row["max_id"] or 0

    def get_unconsolidated(self, session_id: str, working_size: int) -> list[Message]:
        """Return messages that have fallen outside the working window and
        haven't been consolidated into long-term memory yet."""
        with self._conn() as con:
            reset_row = con.execute(
                "SELECT MAX(id) as last_id FROM messages "
                "WHERE session_id = ? AND role = 'session_reset'",
                (session_id,),
            ).fetchone()
            after_id = reset_row["last_id"] or 0

            mark_row = con.execute(
                "SELECT max_message_id FROM consolidated_marks WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            last_consolidated = mark_row["max_message_id"] if mark_row else 0

            max_row = con.execute(
                "SELECT MAX(id) as max_id FROM messages "
                "WHERE session_id = ? AND id > ? "
                "AND role IN ('user', 'assistant')",
                (session_id, after_id),
            ).fetchone()
            max_id = max_row["max_id"] or 0

            # The window boundary: everything older than the last `working_size` rows
            cutoff_id = max_id - working_size
            if cutoff_id <= last_consolidated or cutoff_id <= after_id:
                return []

            rows = con.execute(
                "SELECT role, content, tool_calls, tool_call_id, name "
                "FROM messages WHERE session_id = ? AND id > ? AND id <= ? "
                "AND role IN ('user', 'assistant') ORDER BY id",
                (session_id, max(after_id, last_consolidated), cutoff_id),
            ).fetchall()

        messages: list[Message] = []
        for row in rows:
            if row["content"]:
                messages.append(Message(role=row["role"], content=row["content"]))
        return messages

    def mark_consolidated(self, session_id: str, up_to_id: int) -> None:
        """Record that messages up to and including up_to_id have been consolidated."""
        with self._conn() as con:
            con.execute(
                "INSERT INTO consolidated_marks (session_id, max_message_id) VALUES (?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET max_message_id = MAX(max_message_id, excluded.max_message_id)",
                (session_id, up_to_id),
            )

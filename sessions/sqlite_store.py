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

    def get_history(self, session_id: str) -> list[Message]:
        with self._conn() as con:
            # Find the id of the most recent reset marker, if any
            reset_row = con.execute(
                "SELECT MAX(id) as last_id FROM messages "
                "WHERE session_id = ? AND role = 'session_reset'",
                (session_id,),
            ).fetchone()
            after_id = reset_row["last_id"] or 0

            rows = con.execute(
                "SELECT role, content, tool_calls, tool_call_id, name "
                "FROM messages WHERE session_id = ? AND id > ? AND role IN ('system', 'user', 'assistant', 'tool') ORDER BY id",
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

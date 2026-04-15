from __future__ import annotations

import asyncio
import json
from fastapi import WebSocket
from core.events import EmotionState

HEARTBEAT_INTERVAL_SECONDS = 5.0


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._last_state: EmotionState = EmotionState.IDLE
        self._last_detail: str | None = None
        self._heartbeat_task: asyncio.Task | None = None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)
        # Replay last known state so new connections aren't blank
        await websocket.send_json({
            "type": "state",
            "state": self._last_state.value,
            "detail": self._last_detail,
        })

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    def start_heartbeat(self) -> None:
        """Start the periodic ping task. Idempotent — safe to call more than once."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            return
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            await self._send_ping()

    async def _send_ping(self) -> None:
        if not self._connections:
            return
        await self._send_all({"type": "ping"})

    async def broadcast(self, state: EmotionState, detail: str | None = None) -> None:
        self._last_state = state
        self._last_detail = detail
        await self._send_all({"type": "state", "state": state.value, "detail": detail})

    async def _send_all(self, payload: dict) -> None:
        """Send a JSON payload to all connections, pruning any dead ones."""
        message = json.dumps(payload)
        dead_connections = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead_connections.append(ws)
        for ws in dead_connections:
            self._connections.remove(ws)


manager = ConnectionManager()

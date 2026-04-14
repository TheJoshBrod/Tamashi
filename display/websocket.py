from __future__ import annotations

import json
from fastapi import WebSocket
from core.events import EmotionState


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._last_state: EmotionState = EmotionState.IDLE
        self._last_detail: str | None = None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)
        # Replay last known state so new connections aren't blank
        await websocket.send_json({
            "state": self._last_state.value,
            "detail": self._last_detail,
        })

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, state: EmotionState, detail: str | None = None) -> None:
        self._last_state = state
        self._last_detail = detail
        message = json.dumps({"state": state.value, "detail": detail})
        dead_connections = []
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead_connections.append(ws)
        for ws in dead_connections:
            self._connections.remove(ws)


manager = ConnectionManager()

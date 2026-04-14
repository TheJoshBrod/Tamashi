from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from display.websocket import manager

router = APIRouter(prefix="/display", tags=["display"])
STATIC_DIR = Path(__file__).parent / "static"


@router.get("/")
async def display_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/static/{filename}")
async def static_file(filename: str) -> FileResponse:
    return FileResponse(STATIC_DIR / filename)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

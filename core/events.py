from __future__ import annotations

import asyncio
from enum import Enum
from typing import Callable, Awaitable


class EmotionState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    WORKING = "working"
    SEARCHING = "searching"
    CALCULATING = "calculating"
    DELEGATING = "delegating"
    SUCCESS = "success"
    CONFUSED = "confused"
    ERROR = "error"
    NUTRITION = "nutrition"


class EventBus:
    def __init__(self) -> None:
        self._listeners: list[Callable[[dict], Awaitable[None]]] = []
        self._main_loop: asyncio.AbstractEventLoop | None = None

    def set_main_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._main_loop = loop

    def subscribe(self, callback: Callable[[dict], Awaitable[None]]) -> None:
        self._listeners.append(callback)

    def emit(self, payload: dict) -> None:
        """Thread-safe emit. Schedules delivery on the captured main loop.

        Safe to call from any thread (including asyncio.to_thread workers).
        Drops silently if the main loop hasn't been set yet (startup race).
        """
        if self._main_loop is None:
            return
        self._main_loop.call_soon_threadsafe(
            lambda: self._main_loop.create_task(self._process_event(payload))
        )

    async def _process_event(self, payload: dict) -> None:
        for listener in self._listeners:
            try:
                await listener(payload)
            except Exception:
                pass  # one bad listener must not break others


event_bus = EventBus()

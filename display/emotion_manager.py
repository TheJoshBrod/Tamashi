from __future__ import annotations

import asyncio
import time
from core.events import event_bus, EmotionState

# Maps exact tool function names to display states.
# Subagent delegates (delegate_to_<name>_subagent) are handled by prefix check below.
TOOL_REACTIONS: dict[str, EmotionState] = {
    "web_search": EmotionState.SEARCHING,
    "calculator": EmotionState.CALCULATING,
    "get_current_time": EmotionState.WORKING,
    "open_browser": EmotionState.WORKING,
}

# Replies matching this set (after normalisation) skip the Haiku classifier call.
TRIVIAL_REPLIES = {"ok", "okay", "done", "sure", "yes", "no", "got it", "thanks"}

IDLE_DELAY_SECONDS = 3.0
MIN_HOLD_TIME_SECONDS = 1.0

# States that should be held for at least MIN_HOLD_TIME_SECONDS
WORK_STATES = {
    EmotionState.LISTENING,
    EmotionState.THINKING,
    EmotionState.WORKING,
    EmotionState.SEARCHING,
    EmotionState.CALCULATING,
    EmotionState.DELEGATING,
    EmotionState.NUTRITION,
}

# States that should bypass any pending hold and display immediately.
TERMINAL_STATES = {
    EmotionState.SUCCESS,
    EmotionState.ERROR,
    EmotionState.CONFUSED,
    EmotionState.IDLE,
}


class EmotionManager:
    """Centralised UI policy layer.

    Subscribes to the EventBus, translates domain events into EmotionStates,
    and drives the WebSocket ConnectionManager. All display decisions live here.
    """

    def __init__(self) -> None:
        self._idle_task: asyncio.Task | None = None
        self._hold_timer_task: asyncio.Task | None = None

        self._current_state: EmotionState = EmotionState.IDLE
        self._last_push_time: float = 0
        self._hold_until: float = 0

        self._base_emotion: EmotionState = EmotionState.THINKING
        self._next_push: tuple[EmotionState, str | None] | None = None

        event_bus.subscribe(self._on_event)

    async def _on_event(self, payload: dict) -> None:
        # Every incoming event cancels a pending IDLE transition.
        self._cancel_idle_timer()

        kind = payload.get("event")

        if kind == "MESSAGE_RECEIVED":
            await self._push(EmotionState.LISTENING)

        elif kind == "AGENT_THINKING":
            self._base_emotion = EmotionState.THINKING
            await self._push(EmotionState.THINKING)

        elif kind == "TOOL_STARTED":
            name = payload["tool"]
            if name == "delegate_to_nutrition_subagent":
                self._base_emotion = EmotionState.NUTRITION
                await self._push(EmotionState.NUTRITION, detail=name)
            elif name.startswith("delegate_to_") and name.endswith("_subagent"):
                self._base_emotion = EmotionState.DELEGATING
                await self._push(EmotionState.DELEGATING, detail=name)
            else:
                state = TOOL_REACTIONS.get(name, EmotionState.WORKING)
                await self._push(state, detail=name)

        elif kind == "TOOL_COMPLETED":
            if payload.get("is_error"):
                await self._push(EmotionState.ERROR, detail=payload.get("tool"))
            else:
                # Snap back to the current base emotion (e.g., Nutrition or Thinking)
                await self._push(self._base_emotion)

        elif kind == "AGENT_REPLY_SENT":
            reply = payload.get("reply", "")
            user_text = payload.get("user_text", "")
            emotion = await self._decide_reply_emotion(user_text, reply)
            await self._push(emotion)
            self._schedule_idle()

        elif kind == "SESSION_CLEARED":
            await self._push(EmotionState.SUCCESS, detail="Session cleared")
            self._schedule_idle()

        elif kind == "MAX_ITERATIONS_REACHED":
            await self._push(EmotionState.ERROR, detail="Max iterations")
            self._schedule_idle()

    async def _decide_reply_emotion(self, user_text: str, reply: str) -> EmotionState:
        """Return an emotion for the final reply, skipping the classifier for trivial text."""
        normalized = reply.strip().lower().rstrip(".!?")
        if len(normalized) < 20 and normalized in TRIVIAL_REPLIES:
            return EmotionState.SUCCESS
        from display.emotion_classifier import classify_reply
        return await classify_reply(user_text, reply)

    async def _push(self, state: EmotionState, detail: str | None = None) -> None:
        """Pushes a state to the UI, respecting minimum hold times for work states."""
        loop_time = asyncio.get_event_loop().time()

        # Immediate snap-through for terminal states.
        if state in TERMINAL_STATES:
            self._cancel_hold_timer()
            await self._broadcast(state, detail)
            self._hold_until = 0  # Terminal states don't hold the next state.
            return

        # If we are currently in a hold period, queue the next state.
        if loop_time < self._hold_until:
            self._next_push = (state, detail)
            if not self._hold_timer_task:
                self._hold_timer_task = asyncio.create_task(self._wait_and_push_next())
            return

        # Otherwise, push immediately and set the hold period.
        await self._broadcast(state, detail)
        if state in WORK_STATES:
            self._hold_until = loop_time + MIN_HOLD_TIME_SECONDS
        else:
            self._hold_until = 0

    async def _wait_and_push_next(self) -> None:
        """Internal loop to process queued state transitions after hold times expire."""
        try:
            while self._next_push:
                state, detail = self._next_push
                self._next_push = None

                loop_time = asyncio.get_event_loop().time()
                delay = self._hold_until - loop_time
                if delay > 0:
                    await asyncio.sleep(delay)

                await self._broadcast(state, detail)
                if state in WORK_STATES:
                    self._hold_until = asyncio.get_event_loop().time() + MIN_HOLD_TIME_SECONDS
                else:
                    self._hold_until = 0
        except asyncio.CancelledError:
            pass
        finally:
            self._hold_timer_task = None

    async def _broadcast(self, state: EmotionState, detail: str | None) -> None:
        """Perform the actual emission to the UI."""
        self._current_state = state
        self._last_push_time = time.time()
        from display.websocket import manager
        await manager.broadcast(state, detail)

    def _schedule_idle(self) -> None:
        self._cancel_idle_timer()
        self._idle_task = asyncio.create_task(self._idle_after_delay())

    def _cancel_idle_timer(self) -> None:
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = None

    def _cancel_hold_timer(self) -> None:
        if self._hold_timer_task and not self._hold_timer_task.done():
            self._hold_timer_task.cancel()
        self._hold_timer_task = None
        self._next_push = None

    async def _idle_after_delay(self) -> None:
        try:
            await asyncio.sleep(IDLE_DELAY_SECONDS)
            await self._push(EmotionState.IDLE)
        except asyncio.CancelledError:
            pass  # a new event arrived; it owns the current display state


emotion_manager = EmotionManager()

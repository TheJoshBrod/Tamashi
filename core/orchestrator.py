from __future__ import annotations
import asyncio
import typing
from core.config import settings
from core.schemas import Message
from core.events import event_bus
from providers.base import BaseProvider
from sessions.base import SessionStore
from tools.registry import registry
from core.context import session_id_var


class Orchestrator:
    def __init__(self, provider: BaseProvider, store: SessionStore) -> None:
        self._provider = provider
        self._store = store

    async def handle_stream(self, session_id: str, user_text: str) -> typing.AsyncGenerator[str, None]:
        """Stream messages from the LLM, yielding chunks split at natural boundaries."""
        session_id_var.set(session_id)
        event_bus.emit({"event": "MESSAGE_RECEIVED"})

        if user_text.strip().lower() == "/clear":
            self._store.reset(session_id)
            event_bus.emit({"event": "SESSION_CLEARED"})
            yield "Session cleared. Starting fresh!"
            return

        history = self._build_history(session_id, user_text)
        user_msg = Message(role="user", content=user_text)
        self._store.append(session_id, user_msg)

        tool_specs = registry.specs()
        iters = 0

        while iters < settings.max_tool_iters:
            event_bus.emit({"event": "AGENT_THINKING"})
            
            buffer = ""
            full_text = ""
            tool_calls_response = None
            
            async for response in self._provider.generate_stream(history, tool_specs):
                # 1. Handle tool calls (they arrive at the end of the stream)
                if response.wants_tools:
                    tool_calls_response = response
                    break

                # 2. Handle text chunks
                if response.text_delta:
                    chunk = response.text_delta
                    buffer += chunk
                    full_text += chunk
                    
                    # Split on double newlines for real-time delivery
                    if "\n\n" in buffer:
                        parts = buffer.split("\n\n")
                        # Everything but the last part is a complete paragraph
                        for part in parts[:-1]:
                            text_to_yield = part.strip()
                            if text_to_yield:
                                yield text_to_yield
                        # Keep the last part in the buffer
                        buffer = parts[-1]

            # Yield remaining buffer if any
            if buffer.strip():
                yield buffer.strip()

            iters += 1

            if tool_calls_response:
                assistant_msg = Message(role="assistant", tool_calls=tool_calls_response.tool_calls)
                history.append(assistant_msg)
                self._store.append(session_id, assistant_msg)

                for tc in tool_calls_response.tool_calls:
                    event_bus.emit({"event": "TOOL_STARTED", "tool": tc.name})
                    result_text, is_error = self._call_tool(tc.name, tc.arguments)
                    event_bus.emit({
                        "event": "TOOL_COMPLETED",
                        "tool": tc.name,
                        "result": result_text,
                        "is_error": is_error,
                    })
                    tool_result = Message(role="tool", content=result_text, tool_call_id=tc.id, name=tc.name)
                    history.append(tool_result)
                    self._store.append(session_id, tool_result)
                continue

            # Record final full response in history
            assistant_msg = Message(role="assistant", content=full_text)
            self._store.append(session_id, assistant_msg)

            # Fire-and-forget consolidation — runs for all interfaces, not just Twilio
            if settings.long_term_memory_enabled:
                from memory.consolidator import consolidate_if_needed
                asyncio.create_task(consolidate_if_needed(session_id, self._store))
            return

        event_bus.emit({"event": "MAX_ITERATIONS_REACHED"})
        yield "I ran into trouble completing that. Please try again."

    def _call_tool(self, name: str, arguments: dict) -> tuple[str, bool]:
        """Call a tool and return (result_text, is_error)."""
        result = registry.call(name, arguments)
        is_error = result.startswith("Error")
        return result, is_error

    def _build_history(self, session_id: str, user_text: str) -> list[Message]:
        system = [Message(role="system", content=settings.system_prompt)]

        history = self._store.get_history(session_id, limit=settings.working_memory_size)
        return [*system, *history, Message(role="user", content=user_text)]

from __future__ import annotations
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

    def handle(self, session_id: str, user_text: str) -> str:
        """Process an inbound user message and return the assistant's reply."""
        session_id_var.set(session_id)

        event_bus.emit({"event": "MESSAGE_RECEIVED"})

        if user_text.strip().lower() == "/clear":
            self._store.reset(session_id)
            event_bus.emit({"event": "SESSION_CLEARED"})
            return "Session cleared. Starting fresh!"

        # Build history with system prompt prepended
        history = self._build_history(session_id, user_text)

        # Persist the user turn
        user_msg = Message(role="user", content=user_text)
        self._store.append(session_id, user_msg)

        tool_specs = registry.specs()
        iters = 0

        while iters < settings.max_tool_iters:
            event_bus.emit({"event": "AGENT_THINKING"})
            response = self._provider.generate(history, tool_specs)
            iters += 1

            if response.wants_tools:
                # Append the assistant's tool-call message
                assistant_msg = Message(role="assistant", tool_calls=response.tool_calls)
                history.append(assistant_msg)
                self._store.append(session_id, assistant_msg)

                # Dispatch each tool and collect results
                for tc in response.tool_calls:
                    event_bus.emit({"event": "TOOL_STARTED", "tool": tc.name})
                    result_text, is_error = self._call_tool(tc.name, tc.arguments)
                    event_bus.emit({
                        "event": "TOOL_COMPLETED",
                        "tool": tc.name,
                        "result": result_text,
                        "is_error": is_error,
                    })
                    tool_result = Message(
                        role="tool",
                        content=result_text,
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                    history.append(tool_result)
                    self._store.append(session_id, tool_result)

                # Loop: send updated history back to the model
                continue

            # Final text reply — returned to the interface; AGENT_REPLY_SENT is
            # emitted by the interface *after* the message is delivered.
            reply_text = response.text or ""
            assistant_msg = Message(role="assistant", content=reply_text)
            self._store.append(session_id, assistant_msg)
            return reply_text

        # Safety net: if max iterations hit, return a fallback
        event_bus.emit({"event": "MAX_ITERATIONS_REACHED"})
        return "I ran into trouble completing that. Please try again."

    def _call_tool(self, name: str, arguments: dict) -> tuple[str, bool]:
        """Call a tool and return (result_text, is_error)."""
        result = registry.call(name, arguments)
        is_error = result.startswith("Error")
        return result, is_error

    def _build_history(self, session_id: str, user_text: str) -> list[Message]:
        system = Message(role="system", content=settings.system_prompt)
        history = self._store.get_history(session_id)
        return [system, *history, Message(role="user", content=user_text)]

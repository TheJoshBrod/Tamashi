from __future__ import annotations
from abc import ABC, abstractmethod
from core.schemas import Message


class SessionStore(ABC):
    @abstractmethod
    def get_history(self, session_id: str) -> list[Message]:
        """Return ordered message history for a session."""

    @abstractmethod
    def append(self, session_id: str, message: Message) -> None:
        """Persist a single message to the session."""

    @abstractmethod
    def clear(self, session_id: str) -> None:
        """Delete all history for a session."""

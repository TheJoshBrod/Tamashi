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
    def reset(self, session_id: str) -> None:
        """Insert a session boundary marker. History before it is preserved in
        the DB but excluded from future context retrieval."""

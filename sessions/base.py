from __future__ import annotations
from abc import ABC, abstractmethod
from core.schemas import Message


class SessionStore(ABC):
    @abstractmethod
    def get_history(self, session_id: str, limit: int | None = None) -> list[Message]:
        """Return ordered message history for a session.

        If limit is set, returns only the most recent `limit` messages after
        the last session_reset boundary.
        """

    @abstractmethod
    def append(self, session_id: str, message: Message) -> None:
        """Persist a single message to the session."""

    @abstractmethod
    def reset(self, session_id: str) -> None:
        """Insert a session boundary marker. History before it is preserved in
        the DB but excluded from future context retrieval."""

    @abstractmethod
    def get_unconsolidated(self, session_id: str, working_size: int) -> list[Message]:
        """Return messages that have fallen out of the working window and
        haven't been consolidated into long-term memory yet."""

    @abstractmethod
    def get_max_message_id(self, session_id: str) -> int:
        """Return the highest message id for this session (post-reset)."""

    @abstractmethod
    def mark_consolidated(self, session_id: str, up_to_id: int) -> None:
        """Record that messages up to and including up_to_id have been
        consolidated into long-term memory."""

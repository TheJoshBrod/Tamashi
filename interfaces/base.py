from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class InboundMessage:
    session_id: str  # stable identifier for the sender (e.g. phone number)
    text: str


class MessagingInterface(ABC):
    @abstractmethod
    def parse_inbound(self, raw: dict) -> InboundMessage:
        """Extract session_id and text from a raw webhook payload."""

    @abstractmethod
    def format_outbound(self, text: str) -> str:
        """Render a plain-text reply into the wire format expected by the platform."""

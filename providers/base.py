from __future__ import annotations
from abc import ABC, abstractmethod
from core.schemas import Message, ProviderResponse, ToolSpec


class BaseProvider(ABC):
    @abstractmethod
    def generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> ProviderResponse:
        """
        Send messages to the LLM and return either a text reply or
        a list of tool calls to execute.
        """

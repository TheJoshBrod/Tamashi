from abc import ABC, abstractmethod
import typing
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

    @abstractmethod
    def generate_stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> typing.AsyncGenerator[ProviderResponse, None]:
        """
        Stream tokens from the LLM. Yields partial text deltas
        or final tool calls.
        """

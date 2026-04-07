from __future__ import annotations
import json

import litellm

from core.schemas import Message, ProviderResponse, ToolCall, ToolSpec
from providers.base import BaseProvider


class LiteLLMProvider(BaseProvider):
    def __init__(self, model: str, temperature: float = 0.7) -> None:
        self.model = model
        self.temperature = temperature

    def generate(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> ProviderResponse:
        kwargs: dict = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": self.temperature,
        }
        if tools:
            kwargs["tools"] = [t.to_dict() for t in tools]
            kwargs["tool_choice"] = "auto"

        response = litellm.completion(**kwargs)
        choice = response.choices[0]
        msg = choice.message

        # Tool calls requested by the model
        if msg.tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                )
                for tc in msg.tool_calls
            ]
            return ProviderResponse(tool_calls=tool_calls)

        return ProviderResponse(text=msg.content or "")

from __future__ import annotations
import json
import typing

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

    async def generate_stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
    ) -> typing.AsyncGenerator[ProviderResponse, None]:
        kwargs: dict = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": self.temperature,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = [t.to_dict() for t in tools]
            kwargs["tool_choice"] = "auto"

        response = await litellm.acompletion(**kwargs)

        # LiteLLM yields chunks. We need to accumulate tool call arguments if present.
        accumulated_tool_calls: dict[int, dict] = {}

        async for chunk in response:
            choice = chunk.choices[0]
            delta = choice.delta

            # Handle text stream
            if delta.content:
                yield ProviderResponse(text_delta=delta.content)

            # Handle tool calls stream
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in accumulated_tool_calls:
                        accumulated_tool_calls[idx] = {
                            "id": tc_delta.id,
                            "name": tc_delta.function.name,
                            "arguments": "",
                        }
                    if tc_delta.function.arguments:
                        accumulated_tool_calls[idx]["arguments"] += tc_delta.function.arguments

        # Once the stream finishes, if we have tool calls, yield them as a final package
        if accumulated_tool_calls:
            tool_calls = [
                ToolCall(
                    id=data["id"],
                    name=data["name"],
                    arguments=json.loads(data["arguments"]),
                )
                for data in accumulated_tool_calls.values()
            ]
            yield ProviderResponse(tool_calls=tool_calls)

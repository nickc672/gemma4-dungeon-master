from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolCall:
    """Normalized tool call from any provider."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Normalized response from any LLM provider."""
    text: str
    thinking: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


# Canonical internal message format used by AgentLoop.
# Each provider translates to/from this format.
#
# System:    {"role": "system",    "content": str}
# User:      {"role": "user",      "content": str}
# Assistant: {"role": "assistant", "content": str,
#             "tool_calls": [{"id": str, "name": str, "arguments": dict}]}
# Tool:      {"role": "tool",      "tool_call_id": str, "tool_name": str, "content": str}


@runtime_checkable
class LLMProvider(Protocol):
    """
    Protocol for LLM backends.
    Implementations translate the canonical message format to the
    provider's native API and return a normalized LLMResponse.
    """

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
    ) -> LLMResponse: ...


def serialize_arguments(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, separators=(",", ":"), ensure_ascii=True)


__all__ = ["LLMProvider", "LLMResponse", "ToolCall", "serialize_arguments"]

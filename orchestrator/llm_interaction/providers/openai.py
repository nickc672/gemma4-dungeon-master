from __future__ import annotations

import json
import logging
import os
from typing import Any

from .base import LLMResponse, ToolCall

logger = logging.getLogger(__name__)

# Lazily imported so the package doesn't hard-fail if openai isn't installed.
_openai_client: Any = None


def _get_client(api_key: str | None = None) -> Any:
    global _openai_client
    try:
        import openai
    except ImportError as exc:
        raise ImportError(
            "The 'openai' package is required to use the OpenAI provider. "
            "Install it with: pip install openai"
        ) from exc
    resolved_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not resolved_key:
        raise ValueError(
            "OpenAI API key not found. Set the OPENAI_API_KEY environment variable "
            "or pass api_key in the provider config."
        )
    if _openai_client is None:
        _openai_client = openai.OpenAI(api_key=resolved_key)
    return _openai_client


class OpenAIProvider:
    """
    LLM provider backed by the OpenAI API.
    Translates the canonical message format to OpenAI's native format.
    """

    def __init__(self, *, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
    ) -> LLMResponse:
        client = _get_client(self._api_key)
        native_messages = [_to_openai_message(m) for m in messages]
        opts = options or {}

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": native_messages,
        }
        # Map common options
        if "temperature" in opts:
            kwargs["temperature"] = opts["temperature"]
        if "max_tokens" in opts:
            kwargs["max_tokens"] = opts["max_tokens"]
        if "top_p" in opts:
            kwargs["top_p"] = opts["top_p"]
        if tools:
            # Convert to OpenAI tool spec format
            kwargs["tools"] = [_to_openai_tool(t) for t in tools]
            kwargs["tool_choice"] = "auto"

        response = client.chat.completions.create(**kwargs)
        return _parse_response(response)


# ---------------------------------------------------------------------------
# Message format translation
# ---------------------------------------------------------------------------

def _to_openai_message(msg: dict[str, Any]) -> dict[str, Any]:
    role = msg.get("role", "")

    if role == "tool":
        # Canonical: {"role": "tool", "tool_call_id": str, "tool_name": str, "content": str}
        # OpenAI:    {"role": "tool", "tool_call_id": str, "content": str}
        return {
            "role": "tool",
            "tool_call_id": str(msg.get("tool_call_id", "")),
            "content": str(msg.get("content", "")),
        }

    if role == "assistant" and msg.get("tool_calls"):
        # Canonical: [{"id": str, "name": str, "arguments": dict}]
        # OpenAI:    [{"id": str, "type": "function", "function": {"name": str, "arguments": str}}]
        native_calls = [
            {
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=True),
                },
            }
            for tc in msg.get("tool_calls", [])
        ]
        return {
            "role": "assistant",
            "content": msg.get("content") or None,
            "tool_calls": native_calls,
        }

    return {"role": role, "content": str(msg.get("content", ""))}


def _to_openai_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert DMC tool definition (Ollama/OpenAI format) to OpenAI tool spec."""
    if tool.get("type") == "function":
        return tool
    # Already in the right shape most of the time (same schema as OpenAI)
    return {"type": "function", "function": tool.get("function", tool)}


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_response(response: Any) -> LLMResponse:
    try:
        choice = response.choices[0]
    except (AttributeError, IndexError):
        return LLMResponse(text="")

    message = choice.message
    text = str(message.content or "").strip()

    tool_calls: list[ToolCall] = []
    raw_calls = getattr(message, "tool_calls", None) or []
    for idx, tc in enumerate(raw_calls):
        fn = tc.function
        arguments: dict[str, Any] = {}
        try:
            arguments = json.loads(fn.arguments or "{}")
        except (json.JSONDecodeError, AttributeError):
            pass
        tool_calls.append(ToolCall(
            id=str(tc.id or f"call_{idx}"),
            name=str(fn.name or ""),
            arguments=arguments,
        ))

    return LLMResponse(text=text, tool_calls=tool_calls)


__all__ = ["OpenAIProvider"]

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .base import LLMResponse, ToolCall

logger = logging.getLogger(__name__)


class AnthropicProvider:
    """
    LLM provider backed by the Anthropic API.

    Translates the canonical message format into Anthropic's content-block
    format. Supports Claude's extended thinking when 'thinking' is present
    in options (e.g. options={"thinking": {"type": "enabled", "budget_tokens": 5000}}).

    The Anthropic client is cached per-instance and keyed by the API key it
    was constructed with, so swapping the API key (e.g. via the Streamlit
    sidebar) rebuilds the client on the next chat() call.
    """

    def __init__(self, *, api_key: str | None = None) -> None:
        self._api_key = (api_key or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
        self._client: Any = None
        self._client_key: str = ""

    def _get_client(self) -> Any:
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is required to use the Anthropic provider. "
                "Install it with: pip install anthropic"
            ) from exc
        if not self._api_key:
            raise ValueError(
                "Anthropic API key not found. Provide it via the Streamlit sidebar, "
                "set ANTHROPIC_API_KEY, or pass api_key in the provider config."
            )
        if self._client is None or self._client_key != self._api_key:
            self._client = anthropic.Anthropic(api_key=self._api_key)
            self._client_key = self._api_key
        return self._client

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
    ) -> LLMResponse:
        client = self._get_client()
        opts = options or {}

        # Anthropic requires system prompt as a top-level param, not a message.
        system_prompt, native_messages = _split_system(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": native_messages,
            "max_tokens": int(opts.get("max_tokens", 8192)),
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if "temperature" in opts:
            kwargs["temperature"] = float(opts["temperature"])
        if "top_p" in opts:
            kwargs["top_p"] = float(opts["top_p"])
        if "thinking" in opts:
            kwargs["thinking"] = opts["thinking"]
        if tools:
            kwargs["tools"] = [_to_anthropic_tool(t) for t in tools]

        response = client.messages.create(**kwargs)
        return _parse_response(response)


# ---------------------------------------------------------------------------
# Message format translation
# ---------------------------------------------------------------------------

def _split_system(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Extract system message and return (system_text, remaining_messages)."""
    system_parts: list[str] = []
    rest: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "system":
            system_parts.append(str(msg.get("content", "")))
        else:
            rest.append(msg)
    return "\n\n".join(system_parts), rest


def _to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Convert canonical messages to Anthropic's content-block format.
    Tool results must be folded into the following user message as tool_result blocks.
    """
    result: list[dict[str, Any]] = []
    pending_tool_results: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "")

        if role == "tool":
            # Buffer tool results; Anthropic expects them as user-role content blocks.
            pending_tool_results.append({
                "type": "tool_result",
                "tool_use_id": str(msg.get("tool_call_id", "")),
                "content": str(msg.get("content", "")),
            })
            continue

        # Flush any buffered tool results before the next non-tool message.
        if pending_tool_results:
            result.append({"role": "user", "content": list(pending_tool_results)})
            pending_tool_results = []

        if role == "assistant" and msg.get("tool_calls"):
            content_blocks: list[dict[str, Any]] = []
            text = str(msg.get("content", "")).strip()
            if text:
                content_blocks.append({"type": "text", "text": text})
            for tc in msg.get("tool_calls", []):
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc.get("name", ""),
                    "input": tc.get("arguments", {}),
                })
            result.append({"role": "assistant", "content": content_blocks})
        else:
            result.append({"role": role, "content": str(msg.get("content", ""))})

    # Flush any remaining tool results.
    if pending_tool_results:
        result.append({"role": "user", "content": list(pending_tool_results)})

    return result


def _split_system(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Extract system message; return (system_text, anthropic_format_messages)."""
    system_parts: list[str] = []
    rest: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "system":
            system_parts.append(str(msg.get("content", "")))
        else:
            rest.append(msg)
    return "\n\n".join(system_parts), _to_anthropic_messages(rest)


def _to_anthropic_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert DMC tool definition to Anthropic's tool spec."""
    fn = tool.get("function", tool)
    return {
        "name": fn.get("name", ""),
        "description": fn.get("description", ""),
        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
    }


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_response(response: Any) -> LLMResponse:
    text_parts: list[str] = []
    thinking_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    content_blocks = getattr(response, "content", []) or []
    for idx, block in enumerate(content_blocks):
        block_type = getattr(block, "type", None) or (block.get("type") if isinstance(block, dict) else None)

        if block_type == "text":
            raw = getattr(block, "text", "") or (block.get("text", "") if isinstance(block, dict) else "")
            text_parts.append(str(raw))

        elif block_type == "thinking":
            raw = getattr(block, "thinking", "") or (block.get("thinking", "") if isinstance(block, dict) else "")
            thinking_parts.append(str(raw))

        elif block_type == "tool_use":
            if isinstance(block, dict):
                name = block.get("name", "")
                call_id = block.get("id", f"call_{idx}")
                input_data = block.get("input", {})
            else:
                name = getattr(block, "name", "")
                call_id = getattr(block, "id", f"call_{idx}")
                input_data = getattr(block, "input", {}) or {}

            tool_calls.append(ToolCall(
                id=str(call_id),
                name=str(name),
                arguments=dict(input_data) if isinstance(input_data, dict) else {},
            ))

    return LLMResponse(
        text=" ".join(text_parts).strip(),
        thinking=" ".join(thinking_parts).strip(),
        tool_calls=tool_calls,
    )


__all__ = ["AnthropicProvider"]

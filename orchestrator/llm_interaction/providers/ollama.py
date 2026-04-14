from __future__ import annotations

import json
import logging
from typing import Any

import ollama
from ollama import ResponseError

from .base import LLMResponse, ToolCall

logger = logging.getLogger(__name__)


class OllamaProvider:
    """
    LLM provider backed by a local Ollama instance.
    Translates the canonical message format to Ollama's native format.
    """

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
    ) -> LLMResponse:
        native_messages = [_to_ollama_message(m) for m in messages]

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": native_messages,
            "options": options or {},
        }
        if tools:
            kwargs["tools"] = tools

        try:
            response = ollama.chat(**kwargs)
        except ResponseError as exc:
            raw = _extract_raw_from_error(exc)
            if raw:
                return LLMResponse(text=raw.strip())
            raise

        return _parse_response(response)


# ---------------------------------------------------------------------------
# Message format translation
# ---------------------------------------------------------------------------

def _to_ollama_message(msg: dict[str, Any]) -> dict[str, Any]:
    role = msg.get("role", "")

    if role == "tool":
        # Canonical: {"role": "tool", "tool_call_id": str, "tool_name": str, "content": str}
        # Ollama:    {"role": "tool", "tool_name": str, "content": str}
        return {
            "role": "tool",
            "tool_name": msg.get("tool_name", ""),
            "content": str(msg.get("content", "")),
        }

    if role == "assistant" and msg.get("tool_calls"):
        # Canonical tool_calls: [{"id": str, "name": str, "arguments": dict}]
        # Ollama tool_calls:    [{"function": {"name": str, "arguments": dict}}]
        native_calls = [
            {
                "id": tc.get("id", ""),
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": tc.get("arguments", {}),
                },
            }
            for tc in msg.get("tool_calls", [])
        ]
        return {
            "role": "assistant",
            "content": str(msg.get("content", "")),
            "tool_calls": native_calls,
        }

    return {"role": role, "content": str(msg.get("content", ""))}


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_response(response: Any) -> LLMResponse:
    message = getattr(response, "message", None)
    if message is None and isinstance(response, dict):
        message = response.get("message")

    if message is None:
        return LLMResponse(text="")

    if hasattr(message, "model_dump"):
        payload = message.model_dump(exclude_none=True)
    elif isinstance(message, dict):
        payload = message
    else:
        return LLMResponse(text="")

    # Text content
    content = payload.get("content", "")
    if isinstance(content, list):
        content = "".join(map(str, content))
    text = str(content).strip()

    # Thinking / reasoning content
    thinking = ""
    for key in ("thinking", "reasoning", "reasoning_content"):
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            value = "".join(map(str, value))
        thinking = str(value).strip()
        if thinking:
            break

    # Tool calls
    raw_tool_calls = payload.get("tool_calls") or []
    tool_calls: list[ToolCall] = []
    for idx, tc in enumerate(raw_tool_calls):
        if hasattr(tc, "model_dump"):
            tc = tc.model_dump(exclude_none=True)
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        name = fn.get("name") or tc.get("name", "")
        arguments = fn.get("arguments") or tc.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        tool_calls.append(ToolCall(
            id=str(tc.get("id") or f"call_{idx}"),
            name=str(name),
            arguments=dict(arguments) if isinstance(arguments, dict) else {},
        ))

    return LLMResponse(text=text, thinking=thinking, tool_calls=tool_calls)


def _extract_raw_from_error(exc: Exception) -> str:
    msg = str(exc)
    marker = "raw='"
    start = msg.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    end = msg.find("'", start)
    return "" if end == -1 else msg[start:end]


__all__ = ["OllamaProvider"]

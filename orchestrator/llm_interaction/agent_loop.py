from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from .providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

DMC_ROLL_REQUIRED_SENTINEL = "__DMC_ROLL_REQUIRED__"


class LLMError(RuntimeError):
    """Raised when the LLM fails after retries."""


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

@dataclass
class AgentHooks:
    """
    Optional lifecycle callbacks that control the agent loop.

    Each hook returns None to allow the loop to continue, or a non-empty
    string reason to block / redirect the model.
    """
    # Called before every tool execution. Return {"allow": False, "reason": ...} to block.
    pre_tool_use: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None

    # Called after every tool execution. Return a string note to inject into the conversation.
    post_tool_use: Optional[Callable[[str, Dict[str, Any], Dict[str, Any]], Optional[str]]] = None

    # Called after every assistant response. Return a string reason to reject and retry.
    response_hook: Optional[Callable[[str, Sequence[Dict[str, Any]], int], Optional[str]]] = None

    # Called when the model produces no tool calls (intends to stop).
    # Return a string reason to push the model to continue instead.
    stop_hook: Optional[Callable[[str, bool], Optional[str]]] = None


@dataclass
class AgentResult:
    """The outcome of a completed agent loop run."""
    status: str          # "completed" | "max_iterations"
    final_answer: str
    rounds: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# AgentLoop
# ---------------------------------------------------------------------------

class AgentLoop:
    """
    Provider-agnostic REACT-style agent loop.

    Mirrors the observe → think → act → observe cycle used in tools like
    Claude Code and Copilot Chat:

        1. Send the current conversation to the LLM provider.
        2. If the model requests tool calls, execute them and append results.
        3. If the model produces a plain text response, run optional stop
           hooks; if none block it, return the final answer.
        4. Repeat up to max_iterations.

    All transport is delegated to an LLMProvider implementation, keeping
    this class free of provider-specific logic.
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        model: str,
        default_options: Optional[Dict[str, Any]] = None,
        stage_options: Optional[Dict[str, Dict[str, Any]]] = None,
        max_attempts: int = 3,
        verbose: bool = False,
    ) -> None:
        self.provider = provider
        self.model = model
        self.default_options = dict(default_options or {})
        self.stage_options = dict(stage_options or {})
        self.max_attempts = max(1, max_attempts)
        self.verbose = verbose

    # ------------------------------------------------------------------

    def _options(self, stage: str) -> Dict[str, Any]:
        opts = dict(self.default_options)
        if stage in self.stage_options:
            opts.update(self.stage_options[stage])
        return opts

    def _call(
        self,
        stage: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        options = self._options(stage)
        for attempt in range(1, self.max_attempts + 1):
            if self.verbose:
                print(f"[LLM] {stage} transport attempt {attempt}")
            try:
                return self.provider.chat(
                    model=self.model,
                    messages=messages,
                    tools=tools or [],
                    options=options,
                )
            except Exception as exc:
                if attempt == self.max_attempts:
                    raise LLMError(f"Stage '{stage}' failed after {self.max_attempts} attempts: {exc}") from exc
                if self.verbose:
                    print(f"[LLM-RETRY] {stage} attempt {attempt} failed: {exc}")
        raise LLMError(f"Stage '{stage}' failed after {self.max_attempts} attempts.")

    # ------------------------------------------------------------------

    def request_text(
        self,
        stage: str,
        system_prompt: str,
        payload_text: str,
    ) -> tuple[str, list[dict]]:
        """Single-shot text request (no tool loop). Returns (content, attempt_history)."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": payload_text},
        ]
        attempt_history: list[dict] = []

        for attempt in range(1, self.max_attempts + 1):
            if self.verbose:
                print(f"[LLM] {stage} text attempt {attempt}")
            try:
                response = self.provider.chat(
                    model=self.model,
                    messages=messages,
                    options=self._options(stage),
                )
                content = response.text.strip()
            except Exception as exc:
                content = ""
                if self.verbose:
                    print(f"[LLM-RETRY] {stage} error: {exc}")

            attempt_history.append({"attempt": attempt, "content": content, "success": bool(content)})

            if content:
                if self.verbose:
                    logger.info("[%s] success (%d chars)", stage.upper(), len(content))
                return content, attempt_history

            messages.append({
                "role": "system",
                "content": "Please provide a detailed natural-language response.",
            })

        raise LLMError(f"Stage '{stage}' failed after {self.max_attempts} attempts.")

    # ------------------------------------------------------------------

    def run(
        self,
        *,
        stage: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        tool_executor: Optional[Callable[[str, Mapping[str, Any]], Any]] = None,
        max_iterations: int = 10,
        hooks: Optional[AgentHooks] = None,
    ) -> AgentResult:
        """
        Run the REACT loop until the model stops calling tools or max_iterations
        is reached.

        The conversation starts with [system_prompt + messages] and grows as
        the model and tools exchange turns.
        """
        hooks = hooks or AgentHooks()
        max_iterations = max(1, max_iterations)

        full_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]
        convo: list[dict[str, Any]] = list(full_messages)
        rounds: list[dict[str, Any]] = []
        tool_trace: list[dict[str, Any]] = []
        stop_hook_active = False

        for iteration in range(1, max_iterations + 1):
            if self.verbose:
                print(f"[LOOP] {stage} iteration {iteration}")

            response = self._call(stage, convo, tools=list(tools))

            assistant_text = response.text
            assistant_thinking = response.thinking
            tool_calls = response.tool_calls   # list[ToolCall]

            # Normalised representation for round tracking / hooks
            call_dicts = [
                {"id": tc.id, "name": tc.name, "arguments": copy.deepcopy(tc.arguments)}
                for tc in tool_calls
            ]

            round_info: dict[str, Any] = {
                "iteration": iteration,
                "assistant_text": assistant_text,
                "assistant_thinking": assistant_thinking,
                "tool_calls": call_dicts,
                "tool_results": [],
                "stop_hook_active": stop_hook_active,
                "hook_notes": [],
            }
            rounds.append(round_info)

            # Response hook: may reject and ask the model to retry
            if hooks.response_hook:
                block_reason = hooks.response_hook(assistant_text, call_dicts, iteration)
                if block_reason:
                    round_info["response_block_reason"] = block_reason
                    convo.append({
                        "role": "user",
                        "content": (
                            "Your last response was invalid for this phase: "
                            f"{block_reason} Re-respond and follow the required structure."
                        ),
                    })
                    continue

            # No tool calls → model wants to stop
            if not tool_calls:
                stop_reason = hooks.stop_hook(assistant_text, stop_hook_active) if hooks.stop_hook else None
                if stop_reason:
                    stop_hook_active = True
                    round_info["stop_block_reason"] = stop_reason
                    convo.append({
                        "role": "user",
                        "content": (
                            "You were about to finish, but a stop hook blocked completion: "
                            f"{stop_reason}"
                        ),
                    })
                    continue

                convo.append({"role": "assistant", "content": assistant_text})
                return AgentResult(
                    status="completed",
                    final_answer=assistant_text,
                    rounds=rounds,
                    messages=convo,
                    tool_calls=tool_trace,
                )

            # Append assistant turn (with tool calls in canonical format)
            convo.append({
                "role": "assistant",
                "content": assistant_text,
                "tool_calls": copy.deepcopy(call_dicts),
            })

            # Execute each tool call
            for tc in tool_calls:
                tool_name = tc.name
                arguments = tc.arguments

                if hooks.pre_tool_use:
                    pre_result = hooks.pre_tool_use(tool_name, arguments) or {"allow": True}
                else:
                    pre_result = {"allow": True}

                if not pre_result.get("allow", True):
                    tool_payload: dict[str, Any] = {
                        "ok": False,
                        "error": pre_result.get("reason", "Blocked by pre_tool_use hook."),
                    }
                elif tool_executor is None:
                    tool_payload = {
                        "ok": False,
                        "error": f"No tool executor configured for '{tool_name}'.",
                    }
                else:
                    try:
                        result = tool_executor(tool_name, arguments)
                        if isinstance(result, dict):
                            tool_payload = copy.deepcopy(result)
                        else:
                            tool_payload = {"ok": True, "result": copy.deepcopy(result)}
                    except Exception as exc:
                        # The Streamlit UI signals "wait for player roll" via a
                        # sentinel exception — let it escape the loop untouched.
                        if DMC_ROLL_REQUIRED_SENTINEL in str(exc):
                            raise
                        tool_payload = {"ok": False, "error": str(exc)}

                tool_entry = {
                    "iteration": iteration,
                    "name": tool_name,
                    "arguments": copy.deepcopy(arguments),
                    "result": copy.deepcopy(tool_payload),
                }
                round_info["tool_results"].append(tool_entry)
                tool_trace.append(copy.deepcopy(tool_entry))

                convo.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "tool_name": tool_name,
                    "content": json.dumps(tool_payload, separators=(",", ":"), ensure_ascii=True),
                })

                if hooks.post_tool_use:
                    note = hooks.post_tool_use(tool_name, arguments, tool_payload)
                    if note:
                        round_info["hook_notes"].append(str(note))
                        convo.append({"role": "user", "content": f"Hook note: {note}"})

        return AgentResult(
            status="max_iterations",
            final_answer="Stopped due to max iterations before final response.",
            rounds=rounds,
            messages=convo,
            tool_calls=tool_trace,
        )


__all__ = ["AgentLoop", "AgentHooks", "AgentResult", "LLMError", "DMC_ROLL_REQUIRED_SENTINEL"]

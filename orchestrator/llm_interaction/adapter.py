from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Union

import ollama
from ollama import ResponseError

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when the LLM fails after retries."""


class LLMAdapter:
    """
    Thin gateway around the LLM API.
    Handles transport-level retries and normalization.
    """

    def __init__(
        self,
        model: str,
        *,
        default_options: Optional[Mapping[str, Any]] = None,
        stage_options: Optional[Mapping[str, Mapping[str, Any]]] = None,
        max_attempts: int = 3,
        verbose: bool = False,
        force_retry_stage: Optional[str] = None,  # used ONLY by LLMStep
    ) -> None:

        self.model = model
        self.default_options = dict(default_options or {})
        self.stage_options = dict(stage_options or {})
        self.max_attempts = max(1, max_attempts)
        self.verbose = verbose
        self.force_retry_stage = force_retry_stage

    # -------------------------------------------------

    def request_text(self, stage: str, system_prompt: str, payload_text: str) -> tuple[str, list[dict]]:
        messages = self._build_messages(system_prompt, payload_text)
        options = self._stage_options(stage)

        if self.verbose:
            logger.info("[%s] request started", stage.upper())

        attempt_history = []

        for attempt in range(1, self.max_attempts + 1):
            if self.verbose:
                print(f"[LLM] Attempt {attempt} for stage '{stage}'")

            try:
                response = ollama.chat(model=self.model, messages=messages, options=options)
                content = self._extract_content(response)

            except ResponseError as exc:
                content = self._extract_raw_from_error(exc) or ""

            content = content.strip()
            
            attempt_history.append({
                "attempt": attempt,
                "content": content,
                "success": bool(content)
            })

            if content:
                if self.verbose:
                    logger.info(
                        "[%s] success (%s chars)",
                        stage.upper(),
                        len(content),
                    )
                return content, attempt_history

            # empty → retry
            if self.verbose:
                print(f"[LLM-RETRY] Attempt {attempt} returned empty, retrying...")
            
            messages.append(
                {
                    "role": "system",
                    "content": "Please provide a detailed natural-language response.",
                }
            )

        raise LLMError(f"Stage '{stage}' failed after {self.max_attempts} attempts.")
    # -------------------------------------------------

    def request_json(
        self,
        stage: str,
        system_prompt: str,
        payload: Dict[str, Any],
        *,
        validator: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:

        messages = self._build_messages(
            system_prompt,
            json.dumps(payload, separators=(",", ":")),
        )
        options = self._stage_options(stage)

        if self.verbose:
            logger.info("[%s] JSON request started", stage.upper())

        for attempt in range(1, self.max_attempts + 1):
            response = ollama.chat(
                model=self.model,
                messages=messages,
                format="json",
                options=options,
            )

            raw = self._extract_content(response)

            try:
                data = self._parse_json(raw)

                if validator:
                    validator(data)

                if self.verbose:
                    logger.info("[%s] JSON parsed", stage.upper())

                return data

            except Exception as exc:
                logger.warning("[%s] parse failed: %s", stage.upper(), exc)

                messages.append(
                    {
                        "role": "system",
                        "content": "Output must be valid JSON.",
                    }
                )

        raise LLMError(f"Stage '{stage}' failed to return valid JSON.")

    # -------------------------------------------------

    def _build_messages(self, system_prompt: str, user_payload: str):
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ]

    def _stage_options(self, stage: str) -> Dict[str, Any]:
        options = dict(self.default_options)
        if stage in self.stage_options:
            options.update(self.stage_options[stage])
        return options

    # -------------------------------------------------

    @staticmethod
    def _extract_content(response: Any) -> str:
        message = getattr(response, "message", None)

        if message is None and isinstance(response, dict):
            message = response.get("message")

        if not message:
            return ""

        if hasattr(message, "model_dump"):
            payload = message.model_dump(exclude_none=True)
        elif isinstance(message, dict):
            payload = message
        else:
            return ""

        content = payload.get("content", "")

        if isinstance(content, list):
            content = "".join(map(str, content))

        return str(content)

    @staticmethod
    def _extract_thinking(response: Any) -> str:
        """
        Extract model reasoning/thinking text when the backend provides it.
        Different Ollama models expose this under slightly different keys.
        """
        message = getattr(response, "message", None)

        if message is None and isinstance(response, dict):
            message = response.get("message")

        if not message:
            return ""

        if hasattr(message, "model_dump"):
            payload = message.model_dump(exclude_none=True)
        elif isinstance(message, dict):
            payload = message
        else:
            return ""

        for key in ("thinking", "reasoning", "reasoning_content"):
            value = payload.get(key)
            if value is None:
                continue
            if isinstance(value, list):
                value = "".join(map(str, value))
            text = str(value).strip()
            if text:
                return text
        return ""

    @staticmethod
    def _extract_tool_calls(response: Any) -> list[dict[str, Any]]:
        """
        Normalize Ollama tool calls into a plain list of dicts:
        [{'function': {'name': str, 'arguments': {...}}}, ...]
        """
        message = getattr(response, "message", None)
        if message is None and isinstance(response, dict):
            message = response.get("message")
        if not message:
            return []

        # pydantic model case
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            normalized: list[dict[str, Any]] = []
            for tc in tool_calls:
                if hasattr(tc, "model_dump"):
                    normalized.append(tc.model_dump(exclude_none=True))
                elif isinstance(tc, dict):
                    normalized.append(tc)
            return normalized

        # dict case
        if isinstance(message, dict):
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list):
                return [tc for tc in tool_calls if isinstance(tc, dict)]

        return []

    @staticmethod
    def _normalize_tool_calls(response: Any) -> list[dict[str, Any]]:
        """
        Convert model tool calls into a stable shape:
        [{'id': str, 'name': str, 'arguments': dict, 'raw': dict}, ...]
        """
        normalized: list[dict[str, Any]] = []

        for idx, call in enumerate(LLMAdapter._extract_tool_calls(response)):
            if not isinstance(call, dict):
                continue

            function_payload = call.get("function")
            if isinstance(function_payload, dict):
                name = function_payload.get("name") or call.get("name") or ""
                arguments = function_payload.get("arguments", {})
            else:
                name = call.get("name", "")
                arguments = call.get("arguments", {})

            parsed_arguments: dict[str, Any] = {}

            if isinstance(arguments, str):
                try:
                    loaded = json.loads(arguments)
                    if isinstance(loaded, dict):
                        parsed_arguments = loaded
                except json.JSONDecodeError:
                    parsed_arguments = {}
            elif isinstance(arguments, Mapping):
                parsed_arguments = dict(arguments)

            normalized.append(
                {
                    "id": call.get("id") or f"call_{idx}",
                    "name": str(name),
                    "arguments": parsed_arguments,
                    "raw": call,
                }
            )

        return normalized

    @staticmethod
    def _build_callable_tool_executor(
        tools: Optional[Sequence[Union[Mapping[str, Any], Any, Callable]]],
    ) -> Optional[Callable[[str, Mapping[str, Any]], Any]]:
        tool_map: Dict[str, Callable] = {}
        for tool in tools or []:
            if callable(tool):
                name = getattr(tool, "__name__", "")
                if name:
                    tool_map[name] = tool

        if not tool_map:
            return None

        def _executor(tool_name: str, arguments: Mapping[str, Any]) -> Any:
            func = tool_map.get(tool_name)
            if func is None:
                raise LLMError(f"Unknown callable tool '{tool_name}'")
            return func(**dict(arguments))

        return _executor

    def _chat_with_retry(
        self,
        messages: list[dict[str, Any]],
        options: Dict[str, Any],
        stage: str,
        *,
        tools: Optional[Sequence[Union[Mapping[str, Any], Any, Callable]]] = None,
    ) -> Any:
        for attempt in range(1, self.max_attempts + 1):
            if self.verbose:
                print(f"[LLM] Attempt {attempt} for stage '{stage}'")
            try:
                return ollama.chat(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    options=options,
                )
            except ResponseError as exc:
                raw = self._extract_raw_from_error(exc)
                if raw:
                    return {"message": {"content": raw}}
        raise LLMError(f"Stage '{stage}' failed after {self.max_attempts} attempts.")

    @staticmethod
    def _extract_raw_from_error(exc: Exception) -> Optional[str]:
        msg = str(exc)
        marker = "raw='"
        start = msg.find(marker)
        if start == -1:
            return None
        start += len(marker)
        end = msg.find("'", start)
        return None if end == -1 else msg[start:end]

    # -------------------------------------------------

    def _parse_json(self, raw: str) -> Dict[str, Any]:
        cleaned = self._strip_code_fence(raw)
        return json.loads(cleaned)

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        if text.startswith("```"):
            return "\n".join(
                line for line in text.splitlines()
                if not line.startswith("```")
            ).strip()
        return text

    # --------------------------------------------------

    def request_with_tools(
        self, 
        stage: str, 
        system_prompt: str, 
        messages: list[dict],
        tools: list[dict]
    ) -> dict:
        """
        Makes a request that supports tool calling.
        Returns the full response dict from ollama.
        """
        options = self._stage_options(stage)
        
        if self.verbose:
            logger.info("[%s] tool-enabled request started", stage.upper())
        
        response = self._chat_with_retry(
            messages=[
                {"role": "system", "content": system_prompt},
                *messages,
            ],
            options=options,
            stage=stage,
            tools=tools,
        )
        
        return response

    # --------------------------------------------------

    def run_tool_loop(
        self,
        *,
        stage: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: Sequence[Mapping[str, Any]],
        tool_executor: Optional[Callable[[str, Mapping[str, Any]], Any]] = None,
        max_iterations: int = 10,
        pre_tool_use: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None,
        post_tool_use: Optional[Callable[[str, Dict[str, Any], Dict[str, Any]], Optional[str]]] = None,
        stop_hook: Optional[Callable[[str, bool], Optional[str]]] = None,
    ) -> Dict[str, Any]:
        """
        Generic iterative model->tool->result loop.
        Mirrors Copilot-style orchestration with optional hook controls.
        """
        max_iterations = max(1, max_iterations)
        convo_messages: list[dict[str, Any]] = list(messages)
        rounds: list[dict[str, Any]] = []
        tool_trace: list[dict[str, Any]] = []
        stop_hook_active = False

        for iteration in range(1, max_iterations + 1):
            response = self.request_with_tools(
                stage=stage,
                system_prompt=system_prompt,
                messages=convo_messages,
                tools=list(tools),
            )

            assistant_text = self._extract_content(response).strip()
            assistant_thinking = self._extract_thinking(response).strip()
            tool_calls = self._normalize_tool_calls(response)

            round_info: dict[str, Any] = {
                "iteration": iteration,
                "assistant_text": assistant_text,
                "assistant_thinking": assistant_thinking,
                "tool_calls": [
                    {
                        "id": call["id"],
                        "name": call["name"],
                        "arguments": call["arguments"],
                    }
                    for call in tool_calls
                ],
                "tool_results": [],
                "stop_hook_active": stop_hook_active,
                "hook_notes": [],
            }
            rounds.append(round_info)

            if not tool_calls:
                stop_reason = stop_hook(assistant_text, stop_hook_active) if stop_hook else None
                if stop_reason:
                    stop_hook_active = True
                    round_info["stop_block_reason"] = stop_reason
                    convo_messages.append(
                        {
                            "role": "user",
                            "content": (
                                "You were about to finish, but a stop hook blocked completion: "
                                f"{stop_reason}"
                            ),
                        }
                    )
                    continue

                convo_messages.append({"role": "assistant", "content": assistant_text})
                return {
                    "status": "completed",
                    "final_answer": assistant_text,
                    "rounds": rounds,
                    "messages": convo_messages,
                    "tool_calls": tool_trace,
                }

            convo_messages.append(
                {
                    "role": "assistant",
                    "content": assistant_text,
                    "tool_calls": [call["raw"] for call in tool_calls],
                }
            )

            for call in tool_calls:
                tool_name = call["name"]
                arguments = call["arguments"]

                if pre_tool_use:
                    pre_result = pre_tool_use(tool_name, arguments) or {"allow": True}
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
                        tool_result = tool_executor(tool_name, arguments)
                        if isinstance(tool_result, dict):
                            tool_payload = dict(tool_result)
                        else:
                            tool_payload = {"ok": True, "result": tool_result}
                    except Exception as exc:
                        tool_payload = {"ok": False, "error": str(exc)}

                tool_entry = {
                    "iteration": iteration,
                    "name": tool_name,
                    "arguments": arguments,
                    "result": tool_payload,
                }
                round_info["tool_results"].append(tool_entry)
                tool_trace.append(tool_entry)

                convo_messages.append(
                    {
                        "role": "tool",
                        "tool_name": tool_name,
                        "content": json.dumps(tool_payload, separators=(",", ":"), ensure_ascii=True),
                    }
                )

                if post_tool_use:
                    post_note = post_tool_use(tool_name, arguments, tool_payload)
                    if post_note:
                        round_info.setdefault("hook_notes", []).append(str(post_note))
                        convo_messages.append({"role": "user", "content": f"Hook note: {post_note}"})

        return {
            "status": "max_iterations",
            "final_answer": "Stopped due to max iterations before final response.",
            "rounds": rounds,
            "messages": convo_messages,
            "tool_calls": tool_trace,
        }


__all__ = ["LLMAdapter", "LLMError"]

from __future__ import annotations

"""
LLMAdapter — backward-compatible facade over AgentLoop + LLMProvider.

Existing call-sites (pipeline.py, benchmark/runner.py, step.py) continue to
work unchanged.  Internally all transport and looping is delegated to the
new provider abstraction and AgentLoop.
"""

import json
import logging
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Union

from .agent_loop import AgentHooks, AgentLoop, AgentResult
from .agent_loop import LLMError  # re-exported for call-sites that import it here
from .agent_loop import DMC_ROLL_REQUIRED_SENTINEL  # noqa: F401 — re-exported sentinel
from .providers.base import LLMProvider

logger = logging.getLogger(__name__)


class LLMAdapter:
    """
    Thin facade that presents the original LLMAdapter API while delegating
    all work to AgentLoop and an LLMProvider.

    Provider selection order:
      1. Explicit ``provider`` argument passed at construction time.
      2. Active provider read from app_config (``get_active_provider``).
      3. Falls back to Ollama for backward compatibility.
    """

    def __init__(
        self,
        model: str,
        *,
        provider: Optional[LLMProvider] = None,
        default_options: Optional[Mapping[str, Any]] = None,
        stage_options: Optional[Mapping[str, Mapping[str, Any]]] = None,
        max_attempts: int = 3,
        verbose: bool = False,
        force_retry_stage: Optional[str] = None,  # kept for call-site compat
    ) -> None:
        self._verbose = verbose
        self.force_retry_stage = force_retry_stage  # used by LLMStep only

        if provider is None:
            provider = _default_provider()

        self._loop = AgentLoop(
            provider,
            model=model,
            default_options=dict(default_options or {}),
            stage_options=dict(stage_options or {}),
            max_attempts=max(1, max_attempts),
            verbose=verbose,
        )

    # model is kept in sync with the underlying AgentLoop so external
    # call-sites (Streamlit sidebar, CLI) can swap models mid-session
    # without rebuilding the whole adapter.
    @property
    def model(self) -> str:
        return self._loop.model

    @model.setter
    def model(self, value: str) -> None:
        self._loop.model = str(value)

    @property
    def verbose(self) -> bool:
        return self._verbose

    @verbose.setter
    def verbose(self, value: bool) -> None:
        self._verbose = bool(value)
        self._loop.verbose = bool(value)

    def set_provider(
        self,
        provider: LLMProvider,
        *,
        default_options: Optional[Mapping[str, Any]] = None,
        stage_options: Optional[Mapping[str, Mapping[str, Any]]] = None,
    ) -> None:
        """Swap the underlying provider and its options on the live loop."""
        self._loop.provider = provider
        if default_options is not None:
            self._loop.default_options = dict(default_options)
        if stage_options is not None:
            self._loop.stage_options = dict(stage_options)

    # ------------------------------------------------------------------
    # Single-shot text / JSON helpers (used by LLMStep / narrate / intro)
    # ------------------------------------------------------------------

    def request_text(
        self,
        stage: str,
        system_prompt: str,
        payload_text: str,
    ) -> tuple[str, list[dict]]:
        return self._loop.request_text(stage, system_prompt, payload_text)

    def request_json(
        self,
        stage: str,
        system_prompt: str,
        payload: Dict[str, Any],
        *,
        validator: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Single-shot JSON request with optional validator and retries."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, separators=(",", ":"))},
        ]
        for attempt in range(1, self._loop.max_attempts + 1):
            response = self._loop.provider.chat(
                model=self.model,
                messages=messages,
                options=self._loop._options(stage),
            )
            raw = response.text
            try:
                data = _parse_json(raw)
                if validator:
                    validator(data)
                return data
            except Exception as exc:
                logger.warning("[%s] JSON parse failed: %s", stage.upper(), exc)
                messages.append({"role": "system", "content": "Output must be valid JSON."})

        raise LLMError(f"Stage '{stage}' failed to return valid JSON.")

    # ------------------------------------------------------------------
    # Tool loop (used by pipeline.py)
    # ------------------------------------------------------------------

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
        assistant_response_hook: Optional[Callable[[str, Sequence[Dict[str, Any]], int], Optional[str]]] = None,
        stop_hook: Optional[Callable[[str, bool], Optional[str]]] = None,
        early_exit: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Backward-compatible wrapper around AgentLoop.run().
        Returns the same dict shape as the previous implementation.
        """
        hooks = AgentHooks(
            pre_tool_use=pre_tool_use,
            post_tool_use=post_tool_use,
            response_hook=assistant_response_hook,
            stop_hook=stop_hook,
            early_exit=early_exit,
        )

        result: AgentResult = self._loop.run(
            stage=stage,
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            tool_executor=tool_executor,
            max_iterations=max_iterations,
            hooks=hooks,
        )

        return {
            "status": result.status,
            "final_answer": result.final_answer,
            "rounds": result.rounds,
            "messages": result.messages,
            "tool_calls": result.tool_calls,
        }

    # ------------------------------------------------------------------
    # Legacy single-call helper (kept for any remaining direct usages)
    # ------------------------------------------------------------------

    def request_with_tools(
        self,
        stage: str,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
    ) -> dict:
        """Single-turn tool-capable request (no loop). Returns raw response dict."""
        response = self._loop._call(
            stage,
            [{"role": "system", "content": system_prompt}, *messages],
            tools=tools,
        )
        # Reconstruct a dict that existing callers can inspect
        return {
            "message": {
                "content": response.text,
                "tool_calls": [
                    {"id": tc.id, "function": {"name": tc.name, "arguments": tc.arguments}}
                    for tc in response.tool_calls
                ],
            }
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _default_provider() -> LLMProvider:
    """
    Create a provider from app_config. Falls back to Ollama if config is
    unavailable (e.g. in tests or benchmark runs).
    """
    try:
        from ..app_config import get_default_provider, get_provider_config
        from .providers.factory import create_provider
        name = get_default_provider()
        config = get_provider_config(name)
        return create_provider(name, config)
    except Exception:
        from .providers.ollama import get_shared_instance
        return get_shared_instance()


def _parse_json(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(line for line in text.splitlines() if not line.startswith("```")).strip()
    return json.loads(text)


__all__ = ["LLMAdapter", "LLMError", "DMC_ROLL_REQUIRED_SENTINEL"]

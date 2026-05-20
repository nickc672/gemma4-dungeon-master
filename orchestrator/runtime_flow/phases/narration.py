from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List


@dataclass
class NarrationInput:
    state: Any
    turn_summary: str
    narration_focus: str
    blocked_reason: str
    action_tool_calls: List[Dict[str, Any]]
    phase_one_tool_calls: List[Dict[str, Any]]


@dataclass
class NarrationOutput:
    narrative: str
    prompt: str
    debug: Dict[str, Any]


class NarrationRunner:
    """
    Dependencies:
        adapter:        LLMAdapter
        narrate_step:   the narrate LLMStep from build_steps()
        prompt_builder: callable mirroring build_narrate_prompt's signature
    """

    def __init__(
        self,
        *,
        adapter,
        narrate_step,
        prompt_builder: Callable[..., str],
    ) -> None:
        self.adapter = adapter
        self.narrate_step = narrate_step
        self.prompt_builder = prompt_builder

    def run(self, inp: NarrationInput) -> NarrationOutput:
        prompt = self.prompt_builder(
            inp.state,
            turn_summary=inp.turn_summary,
            narration_focus=inp.narration_focus,
            blocked_reason=inp.blocked_reason,
            action_results=inp.action_tool_calls,
            phase_one_tool_calls=inp.phase_one_tool_calls,
        )

        if self.adapter.verbose:
            print("\n[NARRATE] Generating narrative (pre-write state)")

        narrative, debug = self.narrate_step.run(self.adapter, prompt)

        return NarrationOutput(
            narrative=narrative,
            prompt=prompt,
            debug=debug,
        )


__all__ = ["NarrationRunner", "NarrationInput", "NarrationOutput"]
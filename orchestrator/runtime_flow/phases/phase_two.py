from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence
from ..turn_context import TurnContext
from ..turn_heuristics import _PHASE_2_TOOL_NAME_PATTERN, _extract_labeled_line
from .finalize_validators import compute_phase_two_writes_issues


@dataclass
class PhaseTwoInput:
    state: Any
    player_input: str
    turn_ctx: TurnContext
    game_state: Any
    finalize_payload: Dict[str, Any]
    phase_one_tool_calls: List[Dict[str, Any]]
    narration: str
    action_tool_calls: List[Dict[str, Any]] # input list -this runner appends to its own copy
    world_before: Dict[str, Any]


@dataclass
class PhaseTwoOutput:
    finalize_writes_payload: Dict[str, Any]
    phase_two_tool_calls: List[Dict[str, Any]]
    action_tool_calls: List[Dict[str, Any]] # ONLY the phase-two additions (rolls + writes captured)
    successful_tool_counts: Dict[str, int]
    prompt: str
    loop_result: Dict[str, Any]


_PHASE_TWO_ACTION_TOOLS = frozenset({
    "move_to_location",
    "move_npc",
    "write_memory_tool",
    "move_world_item",
    "create_npc",
    "create_item",
})


class Phase2Runner:
    """
    Dependencies:
        adapter:            LLMAdapter
        execute_world_tool: callable(tool_name, args, game_state) -> result
        find_world_object:  callable(name, game_state) -> object or None
        tool_defs:          Phase 2 tool definitions (without finalize_writes)
        tool_names:         allowed Phase 2 tool names (without finalize_writes)
        finalize_tool_def:  the finalize_writes tool definition
        system_prompt:      the Phase 2 system prompt
        prompt_builder:     callable mirroring build_phase_two_prompt
    """

    def __init__(
        self,
        *,
        adapter,
        execute_world_tool: Callable[[str, Dict[str, Any], Any], Dict[str, Any]],
        find_world_object: Callable[[str, Any], Any],
        tool_defs: Sequence[Dict[str, Any]],
        tool_names: Sequence[str],
        finalize_tool_def: Dict[str, Any],
        system_prompt: str,
        prompt_builder: Callable[..., str],
        max_iterations: int = 10,
    ) -> None:
        self.adapter = adapter
        self.execute_world_tool = execute_world_tool
        self.find_world_object = find_world_object
        self.tool_defs = list(tool_defs) + [finalize_tool_def]
        self.allowed_names = set(tool_names) | {"finalize_writes"}
        self.system_prompt = system_prompt
        self.prompt_builder = prompt_builder
        self.max_iterations = max_iterations

    def run(self, inp: PhaseTwoInput) -> PhaseTwoOutput:
        turn_ctx = inp.turn_ctx
        game_state = inp.game_state
        player_input = inp.player_input
        finalize_payload = inp.finalize_payload

        # Phase 2 collects its own tion_tool_calls so the orchestrator can concat phase-1 plus phase-2 contributions.
        action_tool_calls: List[Dict[str, Any]] = []
        successful_tool_counts: Dict[str, int] = {}

        turn_ctx.phase = "phase_two"
        prompt = self.prompt_builder(
            inp.state,
            turn_summary=finalize_payload.get("turn_summary", ""),
            narration_focus=finalize_payload.get("narration_focus", ""),
            blocked_reason=finalize_payload.get("blocked_reason", ""),
            phase_one_tool_calls=inp.phase_one_tool_calls,
            narration=inp.narration,
            action_results=inp.action_tool_calls,
            world_before=inp.world_before,
            unresolved_targets=turn_ctx.unresolved_interaction_targets,
        )

        def tool_executor(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
            args = dict(arguments or {})
            result = self.execute_world_tool(tool_name, args, game_state)

            success = result.get("ok")
            if success is None:
                success = result.get("success", True)

            turn_ctx.append_tool_call({
                "phase": "phase_two",
                "name": tool_name,
                "arguments": args,
                "result": result,
            })

            if success:
                successful_tool_counts[tool_name] = successful_tool_counts.get(tool_name, 0) + 1

            if tool_name in _PHASE_TWO_ACTION_TOOLS:
                action_tool_calls.append({
                    "phase": "phase_two",
                    "name": tool_name,
                    "arguments": args,
                    "result": result,
                })

            if tool_name in {"move_to_location", "move_npc"} and success:
                turn_ctx.current_location = game_state.player_location

            return result

        def pre_tool_use(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
            _ = arguments
            if tool_name not in self.allowed_names:
                return {
                    "allow": False,
                    "retryable": False,
                    "reason": (
                        f"Tool '{tool_name}' is not available in Phase 2. "
                        "Use only move_to_location, move_npc, write_memory_tool, "
                        "move_world_item, create_npc, create_item, or finalize_writes."
                    ),
                }
            if tool_name == "finalize_writes" and turn_ctx.finalize_writes is not None:
                return {
                    "allow": False,
                    "retryable": False,
                    "reason": (
                        "finalize_writes was already called and succeeded. "
                        "STOP RESPONDING. Do not call finalize_writes again. "
                        "Do not call any more tools."
                    ),
                }
            return {"allow": True}

        def post_tool_use(tool_name: str, arguments: Dict[str, Any], payload: Dict[str, Any]) -> Optional[str]:
            _ = arguments
            success = payload.get("ok")
            if success is None:
                success = payload.get("success", True)
            if success:
                return None
            reason = str(payload.get("reason") or payload.get("error") or "unknown reason")
            if tool_name == "move_to_location":
                return (
                    f"move_to_location failed: {reason}. "
                    "If the destination is unreachable, skip the move and explain in writes_summary."
                )
            if tool_name == "write_memory_tool":
                return f"write_memory_tool failed: {reason}. Retry with a valid entity_name and non-empty memory."
            if tool_name == "move_npc":
                return f"move_npc failed: {reason}. Retry with a valid npc_key and destination, or skip."
            if tool_name == "move_world_item":
                return (
                    f"move_world_item failed: {reason}. "
                    "Retry with a valid item_key, holder_kind ('location' or 'entity'), and holder_key, or skip."
                )
            if tool_name == "create_npc":
                retryable = bool(payload.get("retryable", True))
                if not retryable:
                    return f"create_npc failed and cannot be retried: {reason}. Skip and note in writes_summary."
                return f"create_npc failed: {reason}. Retry with a valid name, or skip if the cap was reached."
            if tool_name == "create_item":
                retryable = bool(payload.get("retryable", True))
                if not retryable:
                    return f"create_item failed and cannot be retried: {reason}. Skip and note in writes_summary."
                return f"create_item failed: {reason}. Retry with a valid name, or skip if the cap was reached."
            return None

        def response_hook(assistant_text: str, tool_calls: Sequence[Dict[str, Any]], _iteration: int) -> Optional[str]:
            text = str(assistant_text or "").strip()
            if len(tool_calls) > 1:
                return "Use at most one tool call per response."
            if not text:
                if tool_calls:
                    return None
                return "Every response must include a `Decision Summary:` line."
            if not _extract_labeled_line(text, "Decision Summary"):
                return "Every response must begin with `Decision Summary: ...`."
            if (
                not tool_calls
                and turn_ctx.finalize_writes is None
                and _PHASE_2_TOOL_NAME_PATTERN.search(text)
            ):
                return (
                    "Detected a tool name written as text instead of called "
                    "as a tool. Issue a real function call."
                )
            return None

        def stop_hook(assistant_text: str, already_fired: bool) -> Optional[str]:
            _ = assistant_text
            if turn_ctx.finalize_writes is None:
                return (
                    "The writer phase is not finished. Call `finalize_writes` "
                    "now with this shape: "
                    '{"writes_summary": "<short summary of writes applied>"}. '
                    "Do not call any other tools first."
                )
            if already_fired:
                return None

            issues = compute_phase_two_writes_issues(
                turn_ctx=turn_ctx,
                player_input=player_input,
                finalize_payload=finalize_payload,
                game_state=game_state,
                find_world_object=self.find_world_object,
            )

            if issues:
                turn_ctx.finalize_writes = None
                return (
                    "Writes incomplete - fix before finalizing:\n"
                    + "\n".join(f"- {issue}" for issue in issues)
                )

            return None

        if self.adapter.verbose:
            print("\n[PHASE_TWO] Running writer phase")

        loop_result = self.adapter.run_tool_loop(
            stage="phase_two",
            system_prompt=self.system_prompt,
            messages=[{"role": "user", "content": prompt}],
            tools=self.tool_defs,
            tool_executor=tool_executor,
            max_iterations=self.max_iterations,
            pre_tool_use=pre_tool_use,
            post_tool_use=post_tool_use,
            assistant_response_hook=response_hook,
            stop_hook=stop_hook,
            early_exit=lambda: turn_ctx.finalize_writes is not None,
        )

        finalize_writes_payload = turn_ctx.finalize_writes or {"writes_summary": ""}
        phase_two_tool_calls = turn_ctx.calls_for_phase("phase_two")

        return PhaseTwoOutput(
            finalize_writes_payload=finalize_writes_payload,
            phase_two_tool_calls=phase_two_tool_calls,
            action_tool_calls=action_tool_calls,
            successful_tool_counts=successful_tool_counts,
            prompt=prompt,
            loop_result=loop_result,
        )


__all__ = ["Phase2Runner", "PhaseTwoInput", "PhaseTwoOutput"]
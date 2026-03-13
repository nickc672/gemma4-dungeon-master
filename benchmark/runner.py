from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.llm_interaction.adapter import LLMAdapter, LLMError
from orchestrator.llm_interaction.prompt_builders import (
    PromptState,
    build_intent_prompt,
    build_intent_phase_prompt,
    build_mechanics_phase_prompt,
    build_narrate_prompt,
)
from orchestrator.llm_interaction.prompt_texts import (
    PHASE_INTENT_SYSTEM_PROMPT,
    PHASE_MECHANICS_SYSTEM_PROMPT,
)
from orchestrator.runtime_flow.step_registry import build_steps

# helpers directly from pipeline
from orchestrator.runtime_flow.pipeline import (
    _extract_labeled_line,
    _extract_labeled_block,
    _extract_bullet_items,
    _todo_specs_from_lines,
    _mentions_unresolved_roll_request,
)

from orchestrator.app_config import get_ollama_default_options, get_ollama_stage_options
from orchestrator.world_state.story import GameState, create_initial_game_state
from orchestrator.world_state.tool_runtime import get_runtime_world_model
from orchestrator.world_state.world_model import WorldModel, build_world_model
from orchestrator.world_state.tools import (
    TOOL_DEFINITIONS,
    TODO_ACTIVE_STATUSES,
    bind_turn_orchestration_ctx,
    clear_turn_orchestration_ctx,
    execute_tool as execute_world_tool,
)

from .test_cases import (
    INTENT_CASES, INTENT_PHASE_CASES,
    MECHANICS_PHASE_CASES, NARRATIVE_REQUIREMENT_CASES,
    IntentCase, IntentPhaseCase,
    MechanicsPhaseCase, NarrativeRequirementCase,
)
from .metrics import (
    Timer,
    score_intent, score_intent_phase,
    score_mechanics_phase, score_narrative_requirement,
    summarize_results,
)


BEAT_LIST: List[str] = build_world_model().beat_list


# ============================================================
# Helpers: game state construction
# ============================================================

def _make_game_state(
    world_model: WorldModel,
    player_location: str,
    beat_index: int = 0,
    discovered_keys: List[str] = None,
    npc_locations: Dict[str, str] = None,
    quest_flags: Dict[str, bool] = None,
) -> GameState:

    player_entity = world_model.get_entity("Player")
    if player_entity is not None:
        player_entity.set_location(player_location)
    world_model.starting_location = player_location

    state = create_initial_game_state(
        starting_location=player_location,
        world_model=world_model,
    )
    state.conversation_history = []
    state.current_beat = min(beat_index, len(BEAT_LIST) - 1)

    setattr(state, "_runtime_world_model", world_model)
    get_runtime_world_model(state)

    state.discovered_keys = set(discovered_keys) if discovered_keys else {player_location}
    state.quest_flags = dict(quest_flags) if quest_flags else {}
    if npc_locations:
        state.npc_locations = dict(npc_locations)

    return state


# ============================================================
# Helpers: PromptState construction
# is a parameter-driven version of StoryEngine._make_state().
# ============================================================

def _make_prompt_state(
    world_model: WorldModel,
    player_location: str,
    player_input: str,
    intent: Dict[str, Any],
    beat_index: int = 0,
    discovered_keys: List[str] = None,
    npc_locations: Dict[str, str] = None,
    quest_flags: Dict[str, bool] = None,
    conversation_history: List[str] = None,
    story_status: str = "",
    session_summary: str = "",
) -> PromptState:

    discovered_keys = set(discovered_keys or [player_location])
    npc_locations = npc_locations or {}
    quest_flags = quest_flags or {}
    idx = min(beat_index, len(BEAT_LIST) - 1)

    beat_current = f"{idx + 1}/{len(BEAT_LIST)}: {BEAT_LIST[idx]}"
    beat_next = BEAT_LIST[idx + 1] if idx + 1 < len(BEAT_LIST) else "None"
    beat_guide = ", ".join(BEAT_LIST)

    history_text = (
        "\n".join(conversation_history) if conversation_history else ""
    )

    scene = world_model.scene_snapshot(player_location)
    scene_description = str(scene.get("description") or "Unknown location")
    connected_locations = [str(k) for k in scene.get("connections", []) if str(k).strip()]
    scene_actors = [
        str(k) for k in scene.get("actors_here", [])
        if str(k).strip() and str(k).strip().lower() != "player"
    ]
    scene_items = [str(k) for k in scene.get("items_here", []) if str(k).strip()]

    #Mirrors StoryEngine._make_state entity_info
    entity_info: Dict[str, Any] = {}

    def apply_relevant_flags(key: str, info: Dict[str, str]) -> Dict[str, str]:
        relevant_flags = {
            flag: val
            for flag, val in quest_flags.items()
            if key.lower().replace(" ", "_") in flag.lower()
        }
        if relevant_flags:
            info["flags"] = ", ".join(
                f"{k}={'yes' if v else 'no'}" for k, v in relevant_flags.items()
            )
        return info

    location = world_model.get_location(player_location)
    if location is not None:
        entity_info[location.key] = apply_relevant_flags(location.key, {
            "node_type": "location",
            "connections": ", ".join(location.connections) if location.connections else "none",
            "location": location.key,
            "discovered": "yes" if location.key in discovered_keys else "no",
        })

    for key in connected_locations:
        adjacent = world_model.get_location(key)
        if adjacent is None:
            continue
        entity_info[adjacent.key] = apply_relevant_flags(adjacent.key, {
            "node_type": "location",
            "connections": ", ".join(adjacent.connections) if adjacent.connections else "none",
            "location": adjacent.key,
            "discovered": "yes" if adjacent.key in discovered_keys else "no",
        })

    for key in scene_actors:
        entity = world_model.get_entity(key)
        if entity is None:
            continue
        info: Dict[str, str] = {
            "node_type": entity.entity_type,
            "location": entity.location,
        }
        if entity.inventory:
            info["inventory"] = ", ".join(entity.inventory)
        entity_info[entity.key] = apply_relevant_flags(entity.key, info)

    for key in scene_items:
        item = world_model.get_item(key)
        if item is None:
            continue
        info = {
            "node_type": "item",
            "location": world_model.location_for_key(item.key) or item.holder_key,
        }
        if item.holder_kind == "entity":
            info["holder"] = item.holder_key
        entity_info[item.key] = apply_relevant_flags(item.key, info)

    return PromptState(
        history_text=history_text,
        beat_current=beat_current,
        beat_next=beat_next,
        beat_guide=beat_guide,
        story_status=story_status,
        session_summary=session_summary,
        intent=intent,
        player_input=player_input,
        current_location=player_location,
        scene_description=scene_description,
        connected_locations=connected_locations,
        scene_actors=scene_actors,
        scene_items=scene_items,
        entity_info=entity_info,
    )


# ============================================================
# Phase tool setup (mirrors pipeline.py phase_tool_names)
# ============================================================

_WORLD_TOOLS_BY_NAME = {
    tool["function"]["name"]: tool
    for tool in TOOL_DEFINITIONS
    if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
}

PHASE_TOOL_NAMES = {
    "intent": [
        "get_world_scene",
        "get_world_story",
        "get_world_location",
        "list_world_locations",
        "list_world_entities",
        "get_world_entity",
        "list_world_items",
        "get_world_item",
        "check_can_interact",
        "get_current_context",
        "list_scene_entities",
        "get_entity_state",
        "retrieve_memory_tool",
        "roll_dice",
        "skill_check",
        "get_recent_skill_checks",
    ],
    "mechanics": [
        "get_world_scene",
        "get_world_story",
        "get_world_location",
        "list_world_locations",
        "list_world_entities",
        "get_world_entity",
        "list_world_items",
        "get_world_item",
        "check_can_interact",
        "get_current_context",
        "list_scene_entities",
        "get_entity_state",
        "retrieve_memory_tool",
        "write_memory_tool",
        "roll_dice",
        "skill_check",
        "get_recent_skill_checks",
        "move_to_location",
        "move_npc",
    ],
}


def _phase_tools(phase_name: str) -> List[Dict[str, Any]]:
    return [
        _WORLD_TOOLS_BY_NAME[name]
        for name in PHASE_TOOL_NAMES.get(phase_name, [])
        if name in _WORLD_TOOLS_BY_NAME
    ]


def _compute_todo_counts(turn_ctx: Dict[str, Any]) -> Dict[str, int]:
    counts = {
        "total": len(turn_ctx.get("todo", [])),
        "pending": 0, "in_progress": 0,
        "done": 0, "skipped": 0, "blocked": 0,
    }
    for item in turn_ctx.get("todo", []):
        status = str(item.get("status", "pending")).strip().lower()
        if status in counts:
            counts[status] += 1
        else:
            counts["pending"] += 1
    return counts


# ============================================================
# Main runner
# ============================================================

class BenchmarkRunner:
    def __init__(self, model: str, verbose: bool = False):
        self.model = model
        self.verbose = verbose
        self.adapter = LLMAdapter(
            model=model,
            default_options=get_ollama_default_options(),
            stage_options=get_ollama_stage_options(),
            max_attempts=3,
            verbose=verbose,
        )
        self.steps = build_steps()

    def _log(self, msg: str):
        if self.verbose:
            print(msg)






    # ----------------------------------------------------------
    # test 1: Intent Parsing
    # ----------------------------------------------------------

    def run_intent_test(self) -> List[Dict]:
        results = []
        print(f"  [intent] Running {len(INTENT_CASES)} cases...")

        for case in INTENT_CASES:
            self._log(f"    {case.id}: {case.description}")
            prompt_input = build_intent_prompt(case.history_text, case.player_input)
            parsed = {}
            attempts = 1
            error = None
            raw_output = ""

            all_attempt_raws = []
            with Timer() as t:
                try:
                    parsed, debug = self.steps["intent"].run(self.adapter, prompt_input)
                    attempts = len(debug.get("attempts", []))
                    all_attempt_raws = [a.get("raw", "") for a in debug.get("attempts", [])]
                    raw_output = all_attempt_raws[-1] if all_attempt_raws else ""
                except Exception as exc:
                    error = str(exc)

            result = score_intent(case, parsed, t.elapsed, attempts)
            result["error"] = error
            result["raw_output"] = raw_output
            result["all_attempt_raws"] = all_attempt_raws
            result["description"] = case.description
            result["player_input"] = case.player_input
            result["input"] = case.player_input
            result["expected"] = {
                "action": case.expected_action,
                "targets": case.expected_targets,
            }
            results.append(result)
            print(f"    {case.id} --> score={result['score']} ({t.elapsed:.2f}s, {attempts} attempt(s))")

        return results






    # ----------------------------------------------------------
    # test 2: Intent Phase
    # ----------------------------------------------------------

    def run_intent_phase_test(self) -> List[Dict]:
        results = []
        print(f"  [intent_phase] Running {len(INTENT_PHASE_CASES)} cases...")

        for case in INTENT_PHASE_CASES:
            self._log(f"    {case.id}: {case.description}")

            world_model = build_world_model()

            game_state = _make_game_state(
                world_model=world_model,
                player_location=case.player_location,
                beat_index=case.beat_index,
                discovered_keys=case.discovered_keys,
                npc_locations=case.npc_locations,
                quest_flags=case.quest_flags,
            )

            turn_ctx: Dict[str, Any] = {
                "phase": "intent",
                "todo": [], "todo_revision": 0, "todo_summary": "",
                "notes": [], "intent_summary": "",
                "mechanics_summary": "", "mechanics_status": "",
                "all_world_tool_calls": [],
                "current_location": case.player_location,
            }
            bind_turn_orchestration_ctx(game_state, turn_ctx)

            state = _make_prompt_state(
                world_model=world_model,
                player_location=case.player_location,
                player_input=case.player_input,
                intent=case.intent,
                beat_index=case.beat_index,
                discovered_keys=case.discovered_keys,
                npc_locations=case.npc_locations,
                quest_flags=case.quest_flags,
                conversation_history=case.conversation_history,
                story_status=case.story_status,
                session_summary=case.session_summary,
            )

            intent_phase_prompt = build_intent_phase_prompt(state)

            world_tools_called: List[Dict[str, Any]] = []

            def phase_tool_executor(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
                args = dict(arguments or {})
                turn_ctx["current_location"] = game_state.player_location
                result = execute_world_tool(tool_name, args, game_state)
                if tool_name in _WORLD_TOOLS_BY_NAME:
                    world_tools_called.append({"name": tool_name, "args": args})
                    turn_ctx["all_world_tool_calls"].append({
                        "phase": "intent", "name": tool_name,
                        "arguments": args, "result": result,
                    })
                return result

            def pre_tool_use(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
                _ = arguments
                if tool_name not in _WORLD_TOOLS_BY_NAME:
                    return {"allow": False, "reason": f"Unknown tool '{tool_name}'."}
                #Mirrors pipeline pre_tool_use: block mutation tools in intent phase.
                intent_blocked = {"move_to_location", "move_npc", "write_memory_tool"}
                if tool_name in intent_blocked:
                    return {"allow": False, "reason": f"{tool_name} is deferred to mechanics phase."}
                return {"allow": True}

            def post_tool_use(tool_name: str, arguments: Dict[str, Any], payload: Dict[str, Any]) -> Optional[str]:
                _ = arguments
                success = payload.get("ok")
                if success is None:
                    success = payload.get("success", True)
                if success:
                    return None
                error_text = str(payload.get("error") or payload.get("reason") or "").lower()
                if "unknown tool" in error_text:
                    return f"Unknown tool `{tool_name}`. Use one of the provided tools."
                return None

            def intent_stop_hook(assistant_text: str, _active: bool) -> Optional[str]:
                #Mirrors pipeline intent_stop_hook exactly.
                if not _extract_labeled_line(assistant_text, "Intent Summary"):
                    return "Intent phase must end with `Intent Summary: ...`."
                todo_lines = _extract_bullet_items(assistant_text, "Todo")
                if not todo_lines:
                    return "Intent phase must include a `Todo:` block with 1-4 bullet items."
                if len(todo_lines) > 4:
                    return "Intent phase todo list must contain at most 4 bullet items."
                return None

            #incremented every time the response hook rejects a response.
            intent_corrections: List[Dict[str, str]] = []

            def assistant_response_hook(
                assistant_text: str,
                tool_calls: List[Dict[str, Any]],
                _iteration: int,
            ) -> Optional[str]:
                #Mirrors pipeline phase_response_hook exactly.
                has_tool_calls = len(tool_calls) > 0
                text = str(assistant_text or "").strip()
                correction = None
                if not text and has_tool_calls:
                    correction = None
                elif text and not _extract_labeled_line(text, "Decision Summary"):
                    correction = "Every response must begin with `Decision Summary: ...`."
                elif not text and not has_tool_calls:
                    correction = "Every non-tool response must include a short `Decision Summary:` line."
                elif len(tool_calls) > 1:
                    correction = "Use at most one tool call per response."
                if correction:
                    intent_corrections.append({"iteration": _iteration, "reason": correction})
                return correction

            error = None
            loop_result: Dict[str, Any] = {}
            iterations = 0

            with Timer() as t:
                try:
                    loop_result = self.adapter.run_tool_loop(
                        stage="phase_intent",
                        system_prompt=PHASE_INTENT_SYSTEM_PROMPT,
                        messages=[{"role": "user", "content": intent_phase_prompt}],
                        tools=_phase_tools("intent"),
                        tool_executor=phase_tool_executor,
                        max_iterations=8,
                        pre_tool_use=pre_tool_use,
                        post_tool_use=post_tool_use,
                        assistant_response_hook=assistant_response_hook,
                        stop_hook=intent_stop_hook,
                    )
                    iterations = len(loop_result.get("rounds", []))
                except Exception as exc:
                    error = str(exc)

            intent_phase_text = str(loop_result.get("final_answer", "") or "").strip()
            intent_summary = _extract_labeled_line(intent_phase_text, "Intent Summary")
            planned_items = _extract_bullet_items(intent_phase_text, "Todo")

            # Mirror pipeline: parse text output to build todo.
            todo_created = False
            todo_items: List[Dict[str, Any]] = []
            if planned_items:
                plan_summary = intent_summary or f"Resolve player action '{case.player_input}'."
                execute_world_tool(
                    "set_turn_todo",
                    {"items": _todo_specs_from_lines(planned_items), "plan_summary": plan_summary},
                    game_state,
                )
                todo_created = True
                todo_items = list(turn_ctx.get("todo", []))

            result = score_intent_phase(
                case=case,
                todo_created=todo_created,
                todo_items=todo_items,
                summary_text=intent_summary,
                tools_called=world_tools_called,
                elapsed=t.elapsed,
                iterations=iterations,
                rounds=loop_result.get("rounds", []),
                error=error,
            )
            result["raw_final"] = intent_phase_text
            result["todo_items"] = todo_items
            result["loop_status"] = loop_result.get("status", "")
            result["corrections"] = intent_corrections
            result["correction_count"] = len(intent_corrections)
            result["input"] = intent_phase_prompt
            result["player_input"] = case.player_input
            result["description"] = case.description
            result["all_rounds"] = loop_result.get("rounds", [])

            results.append(result)
            clear_turn_orchestration_ctx(game_state)

            tag = "OK" if result["all_correct"] else "ISSUES"
            corrections_str = f" corrections={len(intent_corrections)}" if intent_corrections else ""
            print(f"    {case.id} --> score={result['score']} todo={len(todo_items)} items "
                  f"iterations={iterations}{corrections_str} ({t.elapsed:.2f}s) [{tag}]")

        return results






    # ----------------------------------------------------------
    # test 3: Mechanics Phase
    # ----------------------------------------------------------

    def run_mechanics_phase_test(self) -> List[Dict]:
        results = []
        print(f"  [mechanics_phase] Running {len(MECHANICS_PHASE_CASES)} cases...")

        for case in MECHANICS_PHASE_CASES:
            self._log(f"    {case.id}: {case.description}")

            #fresh world model per case
            world_model = build_world_model()

            game_state = _make_game_state(
                world_model=world_model,
                player_location=case.player_location,
                beat_index=case.beat_index,
                discovered_keys=case.discovered_keys,
                npc_locations=case.npc_locations,
                quest_flags=case.quest_flags,
            )

            turn_ctx: Dict[str, Any] = {
                "phase": "mechanics",
                "todo": [], "todo_revision": 0, "todo_summary": "",
                "notes": [], "intent_summary": case.intent_summary,
                "mechanics_summary": "", "mechanics_status": "",
                "all_world_tool_calls": [],
                "current_location": case.player_location,
            }
            bind_turn_orchestration_ctx(game_state, turn_ctx)

            state = _make_prompt_state(
                world_model=world_model,
                player_location=case.player_location,
                player_input=case.player_input,
                intent=case.intent,
                beat_index=case.beat_index,
                discovered_keys=case.discovered_keys,
                npc_locations=case.npc_locations,
                quest_flags=case.quest_flags,
                conversation_history=case.conversation_history,
                story_status=case.story_status,
                session_summary=case.session_summary,
            )

            execute_world_tool(
                "set_turn_todo",
                {"items": case.todo_items, "plan_summary": case.todo_summary},
                game_state,
            )

            mechanics_handoff = build_mechanics_phase_prompt(
                state,
                case.intent_summary,
                turn_ctx["todo"],
            )

            world_tools_called: List[Dict[str, Any]] = []

            def phase_tool_executor(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
                args = dict(arguments or {})
                turn_ctx["current_location"] = game_state.player_location
                result = execute_world_tool(tool_name, args, game_state)
                if tool_name in _WORLD_TOOLS_BY_NAME:
                    world_tools_called.append({"name": tool_name, "args": args})
                    turn_ctx["all_world_tool_calls"].append({
                        "phase": "mechanics", "name": tool_name,
                        "arguments": args, "result": result,
                    })
                if tool_name in {"move_to_location", "move_npc"} and result.get("success"):
                    turn_ctx["current_location"] = game_state.player_location
                return result

            def pre_tool_use(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
                _ = arguments
                if tool_name not in _WORLD_TOOLS_BY_NAME:
                    return {"allow": False, "reason": f"Unknown tool '{tool_name}'."}
                return {"allow": True}

            def post_tool_use(tool_name: str, arguments: Dict[str, Any], payload: Dict[str, Any]) -> Optional[str]:
                _ = arguments
                success = payload.get("ok")
                if success is None:
                    success = payload.get("success", True)
                if success:
                    return None
                error_text = str(payload.get("error") or payload.get("reason") or "").lower()
                if "unknown tool" in error_text:
                    return f"Unknown tool `{tool_name}`. Use one of the provided tools."
                return None

            def mechanics_stop_hook(assistant_text: str, _active: bool) -> Optional[str]:
                #Mirrors pipeline mechanics_stop_hook
                if not _extract_labeled_line(assistant_text, "Mechanics Summary"):
                    return "Mechanics phase must end with `Mechanics Summary: ...`."
                return None

            #incremented every time the response hook rejects a response.
            mechanics_corrections: List[Dict[str, str]] = []

            def assistant_response_hook(
                assistant_text: str,
                tool_calls: List[Dict[str, Any]],
                _iteration: int,
            ) -> Optional[str]:
                #Mirrors pipeline phase_response_hook.
                has_tool_calls = len(tool_calls) > 0
                text = str(assistant_text or "").strip()
                correction = None
                if not text and has_tool_calls:
                    correction = None
                elif text and not _extract_labeled_line(text, "Decision Summary"):
                    correction = "Every response must begin with `Decision Summary: ...`."
                elif not text and not has_tool_calls:
                    correction = "Every non-tool response must include a short `Decision Summary:` line."
                elif len(tool_calls) > 1:
                    correction = "Use at most one tool call per response."
                elif not has_tool_calls and _mentions_unresolved_roll_request(assistant_text):
                    correction = "If a roll/check is needed, call `skill_check` in mechanics. Do not defer player rolls to narration."
                if correction:
                    mechanics_corrections.append({"iteration": _iteration, "reason": correction})
                return correction

            error = None
            loop_result: Dict[str, Any] = {}
            iterations = 0

            with Timer() as t:
                try:
                    loop_result = self.adapter.run_tool_loop(
                        stage="phase_mechanics",
                        system_prompt=PHASE_MECHANICS_SYSTEM_PROMPT,
                        messages=[{"role": "user", "content": mechanics_handoff}],
                        tools=_phase_tools("mechanics"),
                        tool_executor=phase_tool_executor,
                        max_iterations=12,
                        pre_tool_use=pre_tool_use,
                        post_tool_use=post_tool_use,
                        assistant_response_hook=assistant_response_hook,
                        stop_hook=mechanics_stop_hook,
                    )
                    iterations = len(loop_result.get("rounds", []))
                except Exception as exc:
                    error = str(exc)

            if loop_result.get("status") != "completed":
                for item in turn_ctx.get("todo", []):
                    if str(item.get("status", "pending")) in TODO_ACTIVE_STATUSES:
                        item["status"] = "blocked"
                        item["resolution"] = "Mechanics phase reached max iterations."
                        item["used_tool"] = bool(item.get("used_tool", False))
            else:
                for item in turn_ctx.get("todo", []):
                    if str(item.get("status", "pending")) in TODO_ACTIVE_STATUSES:
                        item["status"] = "done"
                        item["used_tool"] = bool(item.get("used_tool", False))

            final_text = str(loop_result.get("final_answer", "") or "").strip()
            summary_text = _extract_labeled_line(final_text, "Mechanics Summary")
            location_after = game_state.player_location
            counts = _compute_todo_counts(turn_ctx)
            all_resolved = (counts.get("pending", 0) + counts.get("in_progress", 0)) == 0
            has_blocked = counts.get("blocked", 0) > 0

            result = score_mechanics_phase(
                case=case,
                tools_called=world_tools_called,
                location_after=location_after,
                all_resolved=all_resolved,
                has_blocked=has_blocked,
                summary_text=summary_text,
                elapsed=t.elapsed,
                iterations=iterations,
                error=error,
            )
            result["raw_final"] = final_text
            result["todo_final"] = json.loads(json.dumps(turn_ctx.get("todo", [])))
            result["todo_counts"] = counts
            result["world_tool_trace"] = turn_ctx.get("all_world_tool_calls", [])
            result["loop_status"] = loop_result.get("status", "")
            result["corrections"] = mechanics_corrections
            result["correction_count"] = len(mechanics_corrections)
            result["input"] = mechanics_handoff
            result["player_input"] = case.player_input
            result["description"] = case.description
            result["all_rounds"] = loop_result.get("rounds", [])

            results.append(result)
            clear_turn_orchestration_ctx(game_state)

            tag = "OK" if result["all_correct"] else "ISSUES"
            corrections_str = f" corrections={len(mechanics_corrections)}" if mechanics_corrections else ""
            print(f"    {case.id} --> score={result['score']} tools={result['actual_tools']} "
                  f"loc={location_after} iterations={iterations}{corrections_str} ({t.elapsed:.2f}s) [{tag}]")

        return results






    # ----------------------------------------------------------
    # test 4: Narrative Requirement
    # ----------------------------------------------------------

    def run_narrative_test(self) -> List[Dict]:
        results = []
        print(f"  [narrative] Running {len(NARRATIVE_REQUIREMENT_CASES)} cases...")
        narrate_step = self.steps["narrate"]

        for case in NARRATIVE_REQUIREMENT_CASES:
            self._log(f"    {case.id}: {case.description}")

            world_model = build_world_model()

            state = _make_prompt_state(
                world_model=world_model,
                player_location=case.player_location,
                player_input=case.player_input,
                intent=case.intent,
                beat_index=case.beat_index,
                discovered_keys=case.discovered_keys,
                npc_locations=case.npc_locations,
                quest_flags=case.quest_flags,
                conversation_history=case.conversation_history,
                story_status=case.story_status,
                session_summary=case.session_summary,
            )
            prompt_input = build_narrate_prompt(
                state, case.plan, case.verdict, case.notes, case.action_results,
            )

            narrative = ""
            attempts = 1
            error = None
            raw_output = ""

            all_attempt_raws = []
            with Timer() as t:
                try:
                    narrative, debug = narrate_step.run(self.adapter, prompt_input)
                    attempts = len(debug.get("attempts", []))
                    all_attempt_raws = [a.get("raw", "") for a in debug.get("attempts", [])]
                    raw_output = all_attempt_raws[-1] if all_attempt_raws else ""
                except Exception as exc:
                    error = str(exc)

            result = score_narrative_requirement(
                case, narrative,
                current_location=case.player_location,
                elapsed=t.elapsed,
                attempts=attempts,
                raw_output=raw_output,
            )
            result["error"] = error
            result["raw_output"] = raw_output
            result["all_attempt_raws"] = all_attempt_raws
            result["player_input"] = case.player_input
            result["description"] = case.description
            result["narrative_full"] = narrative
            result["input"] = prompt_input
            results.append(result)
            print(f"    {case.id} --> score={result['score']} words={result['word_count']} ({t.elapsed:.2f}s)")

        return results







# ============================================================
# Run all tests for one model
# ============================================================

def benchmark_model(
    model: str,
    tests: Optional[List[str]] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    all_tests = ["intent", "intent_phase", "mechanics_phase", "narrative"]
    tests = tests or all_tests

    print(f"\n{'='*60}")
    print(f"  Model: {model}")
    print(f"  Tests: {tests}")
    print(f"{'='*60}")

    runner = BenchmarkRunner(model=model, verbose=verbose)
    test_map = {
        "intent":           runner.run_intent_test,
        "intent_phase":     runner.run_intent_phase_test,
        "mechanics_phase":  runner.run_mechanics_phase_test,
        "narrative":        runner.run_narrative_test,
    }

    test_results: Dict[str, Any] = {}
    overall_start = time.perf_counter()

    for test_name in tests:
        if test_name not in test_map:
            print(f"  [WARNING] Unknown test '{test_name}', skipping")
            continue
        case_results = test_map[test_name]()
        test_results[test_name] = {
            "results": case_results,
            "summary": summarize_results(case_results),
        }

    overall_elapsed = time.perf_counter() - overall_start
    all_results = []
    for s in test_results.values():
        all_results.extend(s["results"])

    return {
        "model": model,
        "timestamp": datetime.now().isoformat(),
        "total_elapsed_s": round(overall_elapsed, 2),
        "tests": test_results,
        "overall": summarize_results(all_results),
    }


# ============================================================
# Output paths
# ============================================================

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def _model_json_path(model: str, timestamp: str) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    safe = model.replace("/", "_").replace(":", "_")
    return OUTPUT_DIR / f"{timestamp}_{safe}_results.json"


def _single_html_path(model: str, timestamp: str) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    safe = model.replace("/", "_").replace(":", "_")
    return OUTPUT_DIR / f"{timestamp}_{safe}_report.html"


# ============================================================
# CLI entry point
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="DM Pipeline Benchmark Runner - runs one model at a time.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Run one model, save JSON + HTML\n"
            "  python3 -m benchmark.runner --model gpt-oss:20b\n\n"
            "  # Run one model, JSON only (skip HTML)\n"
            "  python3 -m benchmark.runner --model llama3.1:8b --no-html\n\n"
            "  # Compare saved JSON files later\n"
            "  python3 -m benchmark.report output/ts_modelA_results.json output/ts_modelB_results.json\n"
        ),
    )
    parser.add_argument(
        "--model", required=True,
        help="Ollama model ID to benchmark (e.g. gpt-oss:20b)",
    )
    parser.add_argument(
        "--tests", nargs="*",
        choices=["intent", "intent_phase", "mechanics_phase", "narrative"],
        default=None,
        help="Which tests to run (default: all four)",
    )
    parser.add_argument(
        "--no-html", action="store_true",
        help="Skip generating an HTML report for this run",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Show detailed LLM output",
    )
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    active_tests = args.tests or ["intent", "intent_phase", "mechanics_phase", "narrative"]
    model = args.model

    try:
        result = benchmark_model(model, tests=active_tests, verbose=args.verbose)
    except Exception as exc:
        print(f"\n[ERROR] Model '{model}' failed: {exc}")
        result = {"error": str(exc), "model": model}

    json_path = _model_json_path(model, timestamp)
    json_path.write_text(json.dumps({model: result}, indent=2), encoding="utf-8")
    print(f"\nResults saved: {json_path}")

    if "error" not in result:
        _print_summary(model, result, active_tests)

    if not args.no_html:
        from .report import generate_report
        html_path = _single_html_path(model, timestamp)
        generate_report({model: result}, str(html_path))
        print(f"Report: {html_path}")
    else:
        print("HTML report skipped (--no-html).")

    print(
        f"\nTo compare with other runs:\n"
        f"  python3 -m benchmark.report {json_path} <other_results.json> ..."
    )


def _print_summary(model: str, data: Dict[str, Any], tests: List[str]):
    overall = data.get("overall", {})
    print(f"\n{'='*60}")
    print(f"  Results: {model}")
    print(f"{'='*60}")
    print(f"  {'Overall score':<20} {overall.get('mean_score', 0):.3f}")
    print(f"  {'Avg response time':<20} {overall.get('mean_elapsed_s', 0):.2f}s")
    print(f"  {'Avg retries':<20} {overall.get('mean_attempts', 0):.2f}")
    print(f"  {'Avg iterations':<20} {overall.get('mean_iterations', 0):.2f}")
    print()
    for test in tests:
        summary = data.get("tests", {}).get(test, {}).get("summary", {})
        score = summary.get("mean_score", 0)
        n = summary.get("n", 0)
        print(f"  {test:<20} {score:.3f}  ({n} cases)")
    failed = overall.get("failed_cases", [])
    if failed:
        print(f"\n  Failed cases: {', '.join(failed)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
from typing import Any, Dict, Sequence, Optional, List, Callable
from .conversation_log import History
from ..llm_interaction.adapter import LLMAdapter
from ..app_config import (
    get_ollama_default_model,
    get_ollama_default_options,
    get_ollama_stage_options,
    get_roll_mode,
)
from .session_state import BeatTracker, SessionSummary, SnapshotBuilder
from .step_registry import build_steps
from ..llm_interaction.prompt_builders import (
    PromptState,
    build_intro_prompt,
    build_intent_prompt,
    build_intent_phase_prompt,
    build_mechanics_phase_prompt,
    build_narrate_prompt,
)
from ..llm_interaction.prompt_texts import (
    PHASE_INTENT_SYSTEM_PROMPT,
    PHASE_MECHANICS_SYSTEM_PROMPT,
)
from ..world_state.story import create_initial_game_state
from ..world_state.tool_runtime import get_runtime_world_model
from ..world_state.world_model import WorldModel, build_world_model, resolve_world_model_data_dir
import json
import re
from ..world_state.tools import (
    TOOL_DEFINITIONS,
    TODO_ACTIVE_STATUSES,
    bind_turn_orchestration_ctx,
    clear_turn_orchestration_ctx,
    execute_tool as execute_world_tool,
)


def _extract_labeled_line(text: str, label: str) -> str:
    pattern = re.compile(rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+?)\s*$")
    match = pattern.search(text or "")
    return match.group(1).strip() if match else ""


def _extract_labeled_block(text: str, label: str) -> str:
    pattern = re.compile(
        rf"(?ims)^\s*{re.escape(label)}\s*:\s*(.*?)(?=^\s*[A-Za-z][A-Za-z _-]*\s*:|\Z)"
    )
    match = pattern.search(text or "")
    return match.group(1).strip() if match else ""


def _extract_bullet_items(text: str, label: str) -> list[str]:
    block = _extract_labeled_block(text, label)
    items: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("- ", "* ")):
            items.append(stripped[2:].strip())
            continue
        numbered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if numbered:
            items.append(numbered.group(1).strip())
    return [item for item in items if item]


def _todo_specs_from_lines(lines: list[str]) -> list[dict[str, Any]]:
    return [{"task": line, "requires_tool": False} for line in lines if str(line).strip()]


def _summary_snippet(text: str, limit: int = 220) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    for sep in (". ", "! ", "? "):
        idx = cleaned.find(sep)
        if 0 < idx < limit:
            return cleaned[: idx + 1]
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def _mentions_unresolved_roll_request(text: str) -> bool:
    cleaned = " ".join(str(text or "").lower().split())
    if not cleaned:
        return False
    markers = (
        "roll",
        "skill check",
        "make a check",
        "passive perception",
        "dc ",
        "investigation check",
        "perception check",
        "stealth check",
        "persuasion check",
        "athletics check",
    )
    return any(marker in cleaned for marker in markers)

class StoryEngine:

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        world_model: Optional[WorldModel] = None,
        world_model_data_dir: Optional[str] = None,
        starting_location: Optional[str] = None,
        beats: Optional[Sequence[str]] = None,
        starting_state: Optional[str] = None,
        verbose: bool = False,
        roll_mode: Optional[str] = None,
        manual_roll_provider: Optional[Callable[[Dict[str, Any]], int]] = None,
    ) -> None:
        self.history = History()
        self.summary = SessionSummary(max_chars=1200)
        self.turn_index = 0
        self.story_status = ""

        self.world = world_model or build_world_model(data_dir=world_model_data_dir)
        source_data_dir = resolve_world_model_data_dir(world_model_data_dir)
        resolved_starting_location = (
            str(starting_location or "").strip()
            or self.world.starting_location
            or "Town Square"
        )
        self.starting_state = str(starting_state or self.world.starting_state or "").strip()
        self.story_status = self.starting_state
        self.beats = BeatTracker(list(beats or self.world.beat_list))
        self.beat_list = list(self.beats.beats)

        self.game_state = create_initial_game_state(
            starting_location=resolved_starting_location,
            world_model=self.world,
            world_model_data_dir=world_model_data_dir,
        )
        setattr(self.game_state, "_world_model_data_dir", str(source_data_dir))
        setattr(self.game_state, "_runtime_world_model", self.world)
        self.world.starting_location = resolved_starting_location
        player_entity = self.world.get_entity("Player")
        if player_entity is not None:
            player_entity.set_location(resolved_starting_location)
        self.game_state.player_location = resolved_starting_location
        self.game_state.discovered_keys = {resolved_starting_location}
        self.discovered_keys = self.game_state.discovered_keys
        get_runtime_world_model(self.game_state)
        self.roll_mode = (roll_mode or get_roll_mode()).strip().lower()
        if self.roll_mode not in {"auto", "manual"}:
            self.roll_mode = "auto"
        self.manual_roll_provider = manual_roll_provider
        if self.roll_mode == "manual" and not callable(self.manual_roll_provider):
            self.roll_mode = "auto"

        resolved_model = model or get_ollama_default_model()

        self.adapter = LLMAdapter(
            model=resolved_model,
            default_options=get_ollama_default_options(),
            stage_options=get_ollama_stage_options(),
            verbose=verbose,
            # force_retry_stage="plan"
        )

        self.steps = build_steps()
        self.snapshot_builder = SnapshotBuilder()

    # -----------------------

    def _make_state(self, player_input, intent):
        def apply_relevant_flags(key: str, info: Dict[str, str]) -> Dict[str, str]:
            relevant_flags = {
                flag: val
                for flag, val in self.game_state.quest_flags.items()
                if key.lower().replace(" ", "_") in flag.lower()
            }
            if relevant_flags:
                info["flags"] = ", ".join(
                    f"{name}={'yes' if value else 'no'}" for name, value in relevant_flags.items()
                )
            return info

        current_location = self.game_state.player_location
        scene = self.world.scene_snapshot(current_location)
        scene_actors = [
            key
            for key in scene.get("actors_here", [])
            if str(key).strip() and str(key).strip().lower() != "player"
        ]
        scene_items = [str(key).strip() for key in scene.get("items_here", []) if str(key).strip()]
        connected_locations = [str(key).strip() for key in scene.get("connections", []) if str(key).strip()]

        entity_info: dict[str, dict[str, str]] = {}

        location = self.world.get_location(current_location)
        if location is not None:
            entity_info[location.key] = apply_relevant_flags(location.key, {
                "node_type": "location",
                "connections": ", ".join(location.connections) if location.connections else "none",
                "location": location.key,
                "discovered": "yes" if location.key in self.game_state.discovered_keys else "no",
            })

        for key in connected_locations:
            adjacent = self.world.get_location(key)
            if adjacent is None:
                continue
            entity_info[adjacent.key] = apply_relevant_flags(adjacent.key, {
                "node_type": "location",
                "connections": ", ".join(adjacent.connections) if adjacent.connections else "none",
                "location": adjacent.key,
                "discovered": "yes" if adjacent.key in self.game_state.discovered_keys else "no",
            })

        for key in scene_actors:
            entity = self.world.get_entity(key)
            if entity is None:
                continue
            info = {
                "node_type": entity.entity_type,
                "location": entity.location,
            }
            if entity.inventory:
                info["inventory"] = ", ".join(entity.inventory)
            entity_info[entity.key] = apply_relevant_flags(entity.key, info)

        for key in scene_items:
            item = self.world.get_item(key)
            if item is None:
                continue
            info = {
                "node_type": "item",
                "location": self.world.location_for_key(item.key) or item.holder_key,
            }
            if item.holder_kind == "entity":
                info["holder"] = item.holder_key
            entity_info[item.key] = apply_relevant_flags(item.key, info)

        return PromptState(
            history_text=self.history.as_text(limit=4),
            beat_current=self.beats.progress_text(),
            beat_next=self.beats.next() or "None",
            beat_guide=", ".join(self.beats.beats),
            story_status=self.story_status,
            session_summary=self.summary.text(),
            intent=intent,
            player_input=player_input,
            current_location=current_location,
            scene_description=str(scene.get("description") or "Unknown location"),
            connected_locations=connected_locations,
            scene_actors=scene_actors,
            scene_items=scene_items,
            entity_info=entity_info,
        )

    # -----------------------

    def run_turn(self, player_input: str):

        trace = {} if self.adapter.verbose else None

        # -----------------------
        # INTENT PARSER (kept from original pipeline)
        # -----------------------

        intent_prompt = build_intent_prompt(
            self.history.as_text(limit=6),
            player_input,
        )

        intent, intent_debug = self.steps["intent"].run(
            self.adapter,
            intent_prompt,
        )

        if trace is not None:
            trace["INTENT_PARSE"] = intent_debug

        # -----------------------
        # BUILD STATE SNAPSHOT
        # -----------------------

        state = self._make_state(player_input, intent)
        def build_state_snapshot():
            scene = self.world.scene_snapshot(self.game_state.player_location)
            return {
                "beat_current": state.beat_current,
                "beat_next": state.beat_next,
                "beat_guide": state.beat_guide,
                "scene": {
                    "current_location": state.current_location,
                    "description": state.scene_description,
                    "connections": list(scene.get("connections", [])),
                    "actors_here": list(scene.get("actors_here", [])),
                    "items_here": list(scene.get("items_here", [])),
                    "status": state.story_status,
                    "session_summary": state.session_summary,
                },
            }

        if trace is not None:
            trace["STATE_BEFORE"] = build_state_snapshot()

        # -----------------------
        # TURN-LOCAL TODO + PHASE TOOLING (Copilot-style agent loops)
        # -----------------------

        turn_ctx: Dict[str, Any] = {
            "phase": "",
            "todo": [],
            "todo_revision": 0,
            "todo_summary": "",
            "notes": [],
            "intent_summary": "",
            "mechanics_summary": "",
            "mechanics_status": "",
            "all_world_tool_calls": [],
            "current_location": self.game_state.player_location,
        }
        action_tool_calls: List[Dict[str, Any]] = []
        bind_turn_orchestration_ctx(self.game_state, turn_ctx)

        world_tools_by_name = {
            tool["function"]["name"]: tool
            for tool in TOOL_DEFINITIONS
            if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
        }

        phase_tool_names = {
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

        def phase_tools(phase_name: str) -> list[dict[str, Any]]:
            return [
                world_tools_by_name[name]
                for name in phase_tool_names.get(phase_name, [])
                if name in world_tools_by_name
            ]

        def compute_todo_counts() -> Dict[str, int]:
            counts = {
                "total": len(turn_ctx["todo"]),
                "pending": 0,
                "in_progress": 0,
                "done": 0,
                "skipped": 0,
                "blocked": 0,
            }
            for item in turn_ctx["todo"]:
                status = str(item.get("status", "pending")).strip().lower()
                if status in counts:
                    counts[status] += 1
                else:
                    counts["pending"] += 1
            return counts

        def phase_tool_executor(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
            args = dict(arguments or {})
            turn_ctx["current_location"] = self.game_state.player_location

            # Hidden runtime behavior: in manual roll mode, the UI/CLI can supply the player's d20
            # while the model still calls normal mechanics tools and receives normal tool payloads.
            manual_roll_supported = False
            if tool_name == "skill_check":
                manual_roll_supported = True
            elif tool_name == "roll_dice":
                try:
                    manual_roll_supported = int(args.get("sides", 20)) == 20 and int(args.get("count", 1)) == 1
                except (TypeError, ValueError):
                    manual_roll_supported = False

            if (
                manual_roll_supported
                and self.roll_mode == "manual"
                and callable(self.manual_roll_provider)
                and "_manual_roll" not in args
            ):
                roll_request = {
                    "tool_name": tool_name,
                    "phase": turn_ctx.get("phase", ""),
                    "arguments": dict(args),
                }
                args["_manual_roll"] = int(self.manual_roll_provider(roll_request))

            result = execute_world_tool(tool_name, args, self.game_state)
            if tool_name in world_tools_by_name:
                world_call_entry = {
                    "phase": turn_ctx.get("phase", ""),
                    "name": tool_name,
                    "arguments": args,
                    "result": result,
                }
                turn_ctx["all_world_tool_calls"].append(world_call_entry)

            if turn_ctx.get("phase") == "mechanics" and tool_name in {
                "move_to_location",
                "move_npc",
                "roll_dice",
                "skill_check",
                "write_memory_tool",
            }:
                action_tool_calls.append({
                    "name": tool_name,
                    "arguments": args,
                    "result": result,
                })

            if tool_name in {"move_to_location", "move_npc"} and result.get("success"):
                turn_ctx["current_location"] = self.game_state.player_location

            return result

        def pre_tool_use(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
            _ = arguments
            phase_name = str(turn_ctx.get("phase", "")).strip().lower()
            if tool_name not in world_tools_by_name:
                return {"allow": False, "reason": f"Unknown tool '{tool_name}'."}

            if phase_name == "intent":
                intent_blocked_tools = {"move_to_location", "move_npc", "write_memory_tool"}
                if tool_name in intent_blocked_tools:
                    return {"allow": False, "reason": f"{tool_name} is deferred to mechanics phase."}

            allowed = set(phase_tool_names.get(phase_name, []))
            if allowed and tool_name not in allowed:
                # Soften phase gating: allow known tools outside preferred list
                # so the loop can recover from imperfect tool selection.
                return {"allow": True}

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

        def phase_response_hook(assistant_text: str, tool_calls: Sequence[Dict[str, Any]], _iteration: int) -> Optional[str]:
            has_tool_calls = len(tool_calls) > 0
            text = str(assistant_text or "").strip()
            if not text and has_tool_calls:
                # Allow tool-only turns. Some models emit an empty assistant text
                # when they decide to call a tool immediately.
                return None
            if text and not _extract_labeled_line(text, "Decision Summary"):
                return "Every response must begin with `Decision Summary: ...`."
            if not text and not has_tool_calls:
                return "Every non-tool response must include a short `Decision Summary:` line."
            if len(tool_calls) > 1:
                return "Use at most one tool call per response."
            if (
                str(turn_ctx.get("phase", "")).strip().lower() == "mechanics"
                and not tool_calls
                and _mentions_unresolved_roll_request(assistant_text)
            ):
                return "If a roll/check is needed, call `skill_check` in mechanics. Do not defer player rolls to narration."
            return None

        def intent_stop_hook(assistant_text: str, _stop_hook_active: bool) -> Optional[str]:
            if not _extract_labeled_line(assistant_text, "Intent Summary"):
                return "Intent phase must end with `Intent Summary: ...`."
            todo_lines = _extract_bullet_items(assistant_text, "Todo")
            if not todo_lines:
                return "Intent phase must include a `Todo:` block with 1-4 bullet items."
            if len(todo_lines) > 4:
                return "Intent phase todo list must contain at most 4 bullet items."
            return None

        def mechanics_stop_hook(assistant_text: str, _stop_hook_active: bool) -> Optional[str]:
            if not _extract_labeled_line(assistant_text, "Mechanics Summary"):
                return "Mechanics phase must end with `Mechanics Summary: ...`."
            return None

        intent_phase_prompt = build_intent_phase_prompt(state)

        turn_ctx["phase"] = "intent"
        intent_loop = self.adapter.run_tool_loop(
            stage="phase_intent",
            system_prompt=PHASE_INTENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": intent_phase_prompt}],
            tools=phase_tools("intent"),
            tool_executor=phase_tool_executor,
            max_iterations=8,
            pre_tool_use=pre_tool_use,
            post_tool_use=post_tool_use,
            assistant_response_hook=phase_response_hook,
            stop_hook=intent_stop_hook,
        )

        intent_phase_text = str(intent_loop.get("final_answer", "") or "").strip()
        turn_ctx["intent_summary"] = _extract_labeled_line(intent_phase_text, "Intent Summary")
        planned_items = _extract_bullet_items(intent_phase_text, "Todo")

        if planned_items:
            plan_summary = turn_ctx["intent_summary"] or f"Resolve player action '{player_input}' with grounded mechanics/state checks."
            execute_world_tool(
                "set_turn_todo",
                {"items": _todo_specs_from_lines(planned_items), "plan_summary": plan_summary},
                self.game_state,
            )
            turn_ctx["intent_summary"] = plan_summary

        if not turn_ctx["todo"]:
            fallback_lines: list[str] = []
            action = str(intent.get("action_category") or intent.get("action") or "other").lower()
            targets = list(intent.get("targets") or [])
            if action == "move" and targets:
                fallback_lines.append(f"Attempt movement to {targets[0]} if it is reachable from the current location.")
            else:
                fallback_lines.append(f"Resolve the player's declared action in context: {player_input}")
            fallback_summary = turn_ctx["intent_summary"] or f"Resolve player action '{player_input}' with grounded mechanics/state checks."
            execute_world_tool(
                "set_turn_todo",
                {"items": _todo_specs_from_lines(fallback_lines), "plan_summary": fallback_summary},
                self.game_state,
            )
            turn_ctx["intent_summary"] = fallback_summary
            if trace is not None:
                trace["INTENT_PHASE_FALLBACK"] = "Generated fallback todo plan because intent phase finished without a plan."

        if not turn_ctx["intent_summary"]:
            turn_ctx["intent_summary"] = turn_ctx.get("todo_summary") or f"Resolve player action: {player_input}"

        intent_todo_snapshot = json.loads(json.dumps(turn_ctx["todo"]))

        mechanics_handoff = build_mechanics_phase_prompt(
            state,
            turn_ctx["intent_summary"],
            turn_ctx["todo"],
        )

        turn_ctx["phase"] = "mechanics"
        mechanics_loop = self.adapter.run_tool_loop(
            stage="phase_mechanics",
            system_prompt=PHASE_MECHANICS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": mechanics_handoff}],
            tools=phase_tools("mechanics"),
            tool_executor=phase_tool_executor,
            max_iterations=12,
            pre_tool_use=pre_tool_use,
            post_tool_use=post_tool_use,
            assistant_response_hook=phase_response_hook,
            stop_hook=mechanics_stop_hook,
        )

        mechanics_phase_text = str(mechanics_loop.get("final_answer", "") or "").strip()

        if mechanics_loop.get("status") != "completed":
            for item in turn_ctx["todo"]:
                if str(item.get("status", "pending")) in TODO_ACTIVE_STATUSES:
                    item["status"] = "blocked"
                    item["resolution"] = "Mechanics phase reached max iterations before resolving this item."
                    item["used_tool"] = bool(item.get("used_tool", False))
            if trace is not None:
                trace["MECHANICS_PHASE_FALLBACK"] = "Mechanics phase hit max iterations; remaining todo items were marked blocked."

        turn_ctx["mechanics_summary"] = _extract_labeled_line(mechanics_phase_text, "Mechanics Summary")
        if not turn_ctx["mechanics_summary"]:
            counts = compute_todo_counts()
            turn_ctx["mechanics_summary"] = (
                "Mechanics phase completed with todo counts "
                + json.dumps(counts, ensure_ascii=True)
            )
        if mechanics_loop.get("status") == "completed":
            for item in turn_ctx["todo"]:
                if str(item.get("status", "pending")) in TODO_ACTIVE_STATUSES:
                    item["status"] = "done"
                    item["resolution"] = turn_ctx["mechanics_summary"]
                    item["used_tool"] = bool(item.get("used_tool", False))

        counts = compute_todo_counts()
        blocked_count = counts.get("blocked", 0)
        turn_ctx["mechanics_status"] = "ITEMS_BLOCKED" if blocked_count > 0 else "ALL_ITEMS_RESOLVED"

        # -----------------------
        # REBUILD STATE WITH UPDATED GAME STATE
        # -----------------------

        if self.adapter.verbose:
            print("\n[STATE] Rebuilding state with updated game state")
            print(f"[STATE] Player location: {self.game_state.player_location}")
            print(f"[STATE] Scene actors: {state.scene_actors}")
            print(f"[STATE] Scene items: {state.scene_items}")

        state = self._make_state(player_input, intent)

        if trace is not None:
            trace["STATE_AFTER_ACTION"] = build_state_snapshot()

        # -----------------------
        # NARRATE (keep existing narrative step + validators)
        # -----------------------

        counts = compute_todo_counts()
        verdict = "revise" if counts.get("blocked", 0) > 0 else "approve"
        notes = turn_ctx["mechanics_summary"]
        if turn_ctx.get("notes"):
            notes = notes + " | Notes: " + " ; ".join(turn_ctx["notes"][-3:])

        narrate_plan = turn_ctx.get("intent_summary") or turn_ctx.get("todo_summary") or player_input
        narrate_prompt = build_narrate_prompt(state, narrate_plan, verdict, notes, action_tool_calls)

        if self.adapter.verbose:
            print("\n[NARRATE] Generating narrative with updated state")

        narrative, narrate_debug = self.steps["narrate"].run(
            self.adapter,
            narrate_prompt,
        )

        # -----------------------
        # COMMIT TURN
        # -----------------------

        self.history.add_player_turn(player_input)
        self.history.add_dm_turn(narrative)
        self.summary.add("Recap", _summary_snippet(narrative))
        self.turn_index += 1

        result = {
            "turn": self.turn_index,
            "narration": {"ic": narrative},
            "intent": intent,
            "beat": self.beats.current(),
            "player_location": self.game_state.player_location,
            "scene": self.world.scene_snapshot(self.game_state.player_location),
            "tool_calls": action_tool_calls,
            "turn_todo": json.loads(json.dumps(turn_ctx["todo"])),
            "phase_summaries": {
                "intent": turn_ctx.get("intent_summary", ""),
                "mechanics": turn_ctx.get("mechanics_summary", ""),
                "mechanics_status": turn_ctx.get("mechanics_status", ""),
            },
        }

        if trace is not None:
            trace["PHASE_INTENT"] = {
                "status": intent_loop.get("status"),
                "prompt": intent_phase_prompt,
                "final_answer": intent_phase_text,
                "rounds": intent_loop.get("rounds", []),
                "todo": intent_todo_snapshot,
            }
            trace["PHASE_MECHANICS"] = {
                "status": mechanics_loop.get("status"),
                "prompt": mechanics_handoff,
                "final_answer": mechanics_phase_text,
                "rounds": mechanics_loop.get("rounds", []),
                "todo_counts": compute_todo_counts(),
            }
            trace["ACTION_TOOLS"] = action_tool_calls
            trace["MECHANICS_WORLD_TOOLS"] = turn_ctx["all_world_tool_calls"]
            trace["TURN_TODO"] = json.loads(json.dumps(turn_ctx["todo"]))
            trace["MOVEMENT_BLOCKED"] = any(
                call.get("name") == "move_to_location" and not call.get("result", {}).get("success", False)
                for call in action_tool_calls
            )
            trace["NARRATE"] = narrate_debug
            trace["STATE_AFTER"] = build_state_snapshot()
            result["llm_trace"] = trace

        clear_turn_orchestration_ctx(self.game_state)
        return result

    # -----------------------
    def generate_intro(self):
        intro_scene = self.world.scene_snapshot(self.game_state.player_location)

        state = PromptState(
            history_text=self.history.as_text(limit=4),
            beat_current=self.beats.progress_text(),
            beat_next=self.beats.next() or "None",
            beat_guide=", ".join(self.beats.beats),
            story_status=self.story_status,
            session_summary=self.summary.text(),
            intent={},
            player_input="",
            current_location=self.game_state.player_location,
            scene_description=str(intro_scene.get("description") or "Unknown location"),
            connected_locations=list(intro_scene.get("connections", [])),
            scene_actors=[
                key
                for key in intro_scene.get("actors_here", [])
                if str(key).strip().lower() != "player"
            ],
            scene_items=list(intro_scene.get("items_here", [])),
            entity_info={},
        )

        prompt = build_intro_prompt(state)

        intro_payload, _ = self.steps["intro"].run(
            self.adapter,
            prompt,
        )
        narrative = str(intro_payload.get("narrative", "")).strip()
        recap = str(intro_payload.get("recap", "")).strip()
        history_intro = recap or _summary_snippet(narrative)

        self.history.add_dm_turn(history_intro or narrative)
        self.summary.add("Intro", recap or _summary_snippet(narrative))

        return {"ic": narrative, "recap": recap}

    # -----------------------

    def snapshot(self):
        return self.snapshot_builder.build(self)

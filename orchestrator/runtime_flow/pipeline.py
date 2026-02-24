from typing import Any, Dict, Sequence, Optional, List, Callable
from .conversation_log import History
from ..world_state.story import StoryGraph, BEAT_LIST, STARTING_STATE
from ..llm_interaction.adapter import LLMAdapter
from ..app_config import (
    get_ollama_default_model,
    get_ollama_default_options,
    get_ollama_stage_options,
    get_roll_mode,
)
from .session_state import BeatTracker, SessionSummary, ActiveKeyManager, FocusManager, SnapshotBuilder
from .step_registry import build_steps
from ..llm_interaction.prompt_builders import (
    PromptState,
    build_intro_prompt,
    build_intent_prompt,
    build_plan_prompt,
    build_narrate_prompt,
)
from ..llm_interaction.prompt_texts import (
    PHASE_INTENT_SYSTEM_PROMPT,
    PHASE_MECHANICS_SYSTEM_PROMPT,
)
from ..world_state.story import create_initial_game_state, NodeType
import json
import re
from ..world_state.tools import (
    TOOL_DEFINITIONS,
    TURN_TODO_TOOL_DEFINITIONS,
    TODO_ACTIVE_STATUSES,
    bind_turn_orchestration_ctx,
    clear_turn_orchestration_ctx,
    execute_tool as execute_world_tool,
)


def _extract_labeled_line(text: str, label: str) -> str:
    pattern = re.compile(rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+?)\s*$")
    match = pattern.search(text or "")
    return match.group(1).strip() if match else ""


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

class StoryEngine:

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        story_graph: Optional[StoryGraph] = None,
        initial_keys: Optional[Sequence[str]] = None,
        beats: Optional[Sequence[str]] = None,
        starting_state: str = STARTING_STATE,
        verbose: bool = False,
        roll_mode: Optional[str] = None,
        manual_roll_provider: Optional[Callable[[Dict[str, Any]], int]] = None,
    ) -> None:

        self.history = History()
        self.summary = SessionSummary(max_chars=1200)
        self.turn_index = 0
        self.story_status = ""

        self.beats = BeatTracker(list(beats or BEAT_LIST))

        self.story = story_graph or StoryGraph(initial_keys=initial_keys)
        self.starting_state = starting_state
        self.current_focus = list(self.story.initial_keys[:1])
        self.discovered_keys = set(self.story.initial_keys)
        self.active_keys = set()

        self.game_state = create_initial_game_state(self.story)
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
        self.focus_manager = FocusManager()
        self.active_manager = ActiveKeyManager()
        self.snapshot_builder = SnapshotBuilder()

        self.active_keys = self.active_manager.refresh(
            self.story,
            self.current_focus,
            beat_text=self.beats.current(),
        )

    # -----------------------

    def _make_state(self, player_input, intent):
        entity_info = {}
        for key in self.active_keys:
            node = self.story.get_node(key)
            if node is None:
                continue

            info = {
                "node_type": node.node_type.value,
                "connections": ", ".join(node.connections) if node.connections else "none",
            }

            if node.node_type == NodeType.LOCATION:
                info["location"] = key
                info["discovered"] = key in self.game_state.discovered_keys

            elif node.node_type == NodeType.NPC:
                #npc_locations first, then fall back to home connection
                info["location"] = (
                    self.game_state.npc_locations.get(key)
                    or (node.connections[0] if node.connections else "unknown")
                )

            elif node.node_type in (NodeType.ITEM, NodeType.CLUE):
                #so the ittems are static and their location is always connections[0]
                info["location"] = node.connections[0] if node.connections else "unknown"

            #any relevant quest flags for this entity
            relevant_flags = {
                flag: val
                for flag, val in self.game_state.quest_flags.items()
                if key.lower().replace(" ", "_") in flag.lower()
            }
            if relevant_flags:
                info["flags"] = ", ".join(
                    f"{k}={'yes' if v else 'no'}" for k, v in relevant_flags.items()
                )

            entity_info[key] = info

        return PromptState(
            history_text=self.history.as_text(limit=8),
            active_keys=sorted(self.active_keys),
            focus=self.current_focus,
            beat_current=self.beats.progress_text(),
            beat_next=self.beats.next() or "None",
            beat_guide=", ".join(self.beats.beats),
            story_status=self.story_status,
            session_summary=self.summary.text(),
            intent=intent,
            player_input=player_input,
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
            trace["INTENT"] = intent_debug
            trace["INTENT_PARSE"] = intent_debug

        # -----------------------
        # REFRESH ACTIVE KEYS + BUILD STATE SNAPSHOT
        # -----------------------

        self.active_keys = self.active_manager.refresh(
            self.story,
            self.current_focus,
            beat_text=self.beats.current(),
        )

        state = self._make_state(player_input, intent)

        def build_state_snapshot():
            return {
                "beat_current": state.beat_current,
                "beat_next": state.beat_next,
                "beat_guide": state.beat_guide,
                "scene": {
                    "location_focus": state.focus,
                    "active_nodes": sorted(self.active_keys),
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
            "current_focus": list(self.current_focus),
            "active_keys": sorted(self.active_keys),
        }
        action_tool_calls: List[Dict[str, Any]] = []
        bind_turn_orchestration_ctx(self.game_state, turn_ctx)

        world_tools_by_name = {
            tool["function"]["name"]: tool
            for tool in TOOL_DEFINITIONS
            if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
        }
        todo_tools_by_name = {
            tool["function"]["name"]: tool
            for tool in TURN_TODO_TOOL_DEFINITIONS
            if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
        }
        all_tool_defs_by_name = {**world_tools_by_name, **todo_tools_by_name}

        phase_tool_names = {
            "intent": [
                "set_turn_todo",
                "get_turn_todo",
                "get_turn_progress",
                "add_turn_note",
                "check_can_interact",
                "get_current_context",
                "list_scene_entities",
                "get_entity_state",
                "retrieve_memory_tool",
            ],
            "mechanics": [
                "get_turn_todo",
                "set_todo_item_status",
                "get_turn_progress",
                "add_turn_note",
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
            ],
        }

        def phase_tools(phase_name: str) -> list[dict[str, Any]]:
            return [
                all_tool_defs_by_name[name]
                for name in phase_tool_names.get(phase_name, [])
                if name in all_tool_defs_by_name
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
            turn_ctx["current_focus"] = list(self.current_focus)
            turn_ctx["active_keys"] = sorted(self.active_keys)

            # Hidden runtime behavior: in manual roll mode, the CLI can supply the player's d20
            # while the model still calls the same `skill_check` tool and receives a normal result.
            if (
                tool_name == "skill_check"
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

            result = execute_world_tool(tool_name, args, self.game_state, self.story)
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

            if tool_name == "move_to_location" and result.get("success"):
                new_location = result.get("new_location")
                if isinstance(new_location, str) and new_location:
                    self.current_focus = [new_location]
                    self.active_keys = self.active_manager.refresh(
                        self.story,
                        self.current_focus,
                        beat_text=self.beats.current(),
                    )
                    turn_ctx["current_focus"] = list(self.current_focus)
                    turn_ctx["active_keys"] = sorted(self.active_keys)

            return result

        def pre_tool_use(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
            phase_name = str(turn_ctx.get("phase", "")).strip().lower()
            allowed = set(phase_tool_names.get(phase_name, []))
            if tool_name not in allowed:
                return {"allow": False, "reason": f"{tool_name} is not available in {phase_name or 'current'} phase."}

            if phase_name == "mechanics" and tool_name in world_tools_by_name:
                if not turn_ctx["todo"]:
                    return {"allow": False, "reason": "No todo plan exists. Read and execute the planned todo list first."}

            return {"allow": True}

        def post_tool_use(tool_name: str, arguments: Dict[str, Any], payload: Dict[str, Any]) -> Optional[str]:
            _ = arguments
            success = payload.get("ok")
            if success is None:
                success = payload.get("success", True)
            if success:
                return None
            if tool_name in world_tools_by_name:
                return "Tool call failed. Mark the todo item blocked or continue with a different tool."
            return "Tool call failed. Correct arguments and continue."

        def intent_stop_hook(assistant_text: str, _stop_hook_active: bool) -> Optional[str]:
            if not str(assistant_text or "").strip():
                return "Intent phase must provide text plus a todo plan."
            if not _extract_labeled_line(assistant_text, "Intent Summary"):
                return "Intent phase must end with `Intent Summary: ...`."
            if int(turn_ctx.get("todo_revision", 0)) <= 0:
                return "Intent phase must call `set_turn_todo` before completion."
            if not turn_ctx.get("todo"):
                return "Intent phase created an empty todo list."
            return None

        def mechanics_stop_hook(assistant_text: str, _stop_hook_active: bool) -> Optional[str]:
            counts = compute_todo_counts()
            pending = counts.get("pending", 0) + counts.get("in_progress", 0)
            if pending > 0:
                return f"Mechanics phase cannot finish with pending todo items ({pending} remaining)."
            if not _extract_labeled_line(assistant_text, "Mechanics Summary"):
                return "Mechanics phase must end with `Mechanics Summary: ...`."
            return None

        intent_phase_prompt = (
            build_plan_prompt(state)
            + "\n\n# Parsed Intent (structured parser output)\n"
            + json.dumps(intent, indent=2)
            + "\n\n# Phase Task\n"
            + "Use tools to inspect context if needed, then create a turn todo list for mechanics execution. "
            + "Do not mutate world state in this phase."
        )

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
            stop_hook=intent_stop_hook,
        )

        intent_phase_text = str(intent_loop.get("final_answer", "") or "").strip()
        turn_ctx["intent_summary"] = _extract_labeled_line(intent_phase_text, "Intent Summary")

        if not turn_ctx["todo"]:
            fallback_items: list[dict[str, Any]] = []
            action = str(intent.get("action_category") or intent.get("action") or "other").lower()
            targets = list(intent.get("targets") or [])
            if action == "move" and targets:
                fallback_items.append(
                    {
                        "task": f"Attempt movement to {targets[0]} if connected.",
                        "requires_tool": True,
                        "tool_name": "move_to_location",
                        "arguments_hint": {"location_key": targets[0]},
                    }
                )
            else:
                fallback_items.append(
                    {
                        "task": f"Resolve the player's declared action in context: {player_input}",
                        "requires_tool": False,
                    }
                )
            fallback_summary = turn_ctx["intent_summary"] or f"Resolve player action '{player_input}' with grounded mechanics/state checks."
            execute_world_tool(
                "set_turn_todo",
                {"items": fallback_items, "plan_summary": fallback_summary},
                self.game_state,
                self.story,
            )
            turn_ctx["intent_summary"] = fallback_summary
            if trace is not None:
                trace["INTENT_PHASE_FALLBACK"] = "Generated fallback todo plan because intent phase finished without a plan."

        if not turn_ctx["intent_summary"]:
            turn_ctx["intent_summary"] = turn_ctx.get("todo_summary") or f"Resolve player action: {player_input}"

        intent_todo_snapshot = json.loads(json.dumps(turn_ctx["todo"]))

        mechanics_handoff = (
            "Phase handoff: intent -> mechanics\n"
            f"Player input: {player_input}\n"
            f"Parsed intent: {json.dumps(intent, ensure_ascii=True)}\n"
            f"Intent summary: {turn_ctx['intent_summary']}\n"
            f"Turn todo revision: {turn_ctx['todo_revision']}\n"
            f"Turn todo items JSON: {json.dumps(turn_ctx['todo'], ensure_ascii=True)}\n"
            "Execute the todo list and mark every item with set_todo_item_status before finishing."
        )

        turn_ctx["phase"] = "mechanics"
        mechanics_loop = self.adapter.run_tool_loop(
            stage="phase_mechanics",
            system_prompt=PHASE_MECHANICS_SYSTEM_PROMPT,
            messages=[*intent_loop.get("messages", []), {"role": "user", "content": mechanics_handoff}],
            tools=phase_tools("mechanics"),
            tool_executor=phase_tool_executor,
            max_iterations=12,
            pre_tool_use=pre_tool_use,
            post_tool_use=post_tool_use,
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

        counts = compute_todo_counts()
        blocked_count = counts.get("blocked", 0)
        turn_ctx["mechanics_status"] = "ITEMS_BLOCKED" if blocked_count > 0 else "ALL_ITEMS_RESOLVED"

        # -----------------------
        # REBUILD STATE WITH UPDATED GAME STATE
        # -----------------------

        if self.adapter.verbose:
            print("\n[STATE] Rebuilding state with updated game state")
            print(f"[STATE] Player location: {self.game_state.player_location}")
            print(f"[STATE] Current focus: {self.current_focus}")
            print(f"[STATE] Active keys: {sorted(self.active_keys)}")

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
            "active_keys": sorted(self.active_keys),
            "focus": self.current_focus,
            "player_location": self.game_state.player_location,
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

        state = PromptState(
            history_text=self.history.as_text(limit=4),
            active_keys=sorted(self.active_keys),
            focus=self.current_focus,
            beat_current=self.beats.progress_text(),
            beat_next=self.beats.next() or "None",
            beat_guide=", ".join(self.beats.beats),
            story_status=self.story_status,
            session_summary=self.summary.text(),
            intent={},
            player_input="",
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

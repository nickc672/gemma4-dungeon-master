from typing import Any, Dict, Sequence, Optional, List, Callable
from .conversation_log import History
from ..llm_interaction.adapter import LLMAdapter
from ..app_config import (
    get_default_provider,
    get_default_model,
    get_provider_default_options,
    get_provider_stage_options,
    get_roll_mode,
)
from .session_state import BeatTracker, SessionSummary, SnapshotBuilder
from .step_registry import build_steps
from ..llm_interaction.prompt_builders import (
    PromptState,
    build_agent_prompt,
    build_intro_prompt,
    build_narrate_prompt,
)
from ..llm_interaction.prompt_texts import AGENT_SYSTEM_PROMPT
from ..world_state.story import create_initial_game_state
from ..world_state.tool_runtime import get_runtime_world_model
from ..world_state.world_model import WorldModel, build_world_model, resolve_world_model_data_dir
import json
import re
from ..world_state.tools import (
    FINALIZE_TURN_TOOL_DEFINITION,
    TOOL_DEFINITIONS,
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


# Keywords that signal player movement intent.
_MOVEMENT_PHRASES = frozenset([
    "go to", "move to", "walk to", "run to", "travel to", "head to",
    "proceed to", "go back", "return to", "head back", "sneak to",
    "creep to", "rush to", "climb to", "go inside", "go outside",
    "enter the", "leave the", "exit the", "go through", "cross to",
])

# Keywords that signal significant NPC interaction in a turn summary.
_INTERACTION_WORDS = frozenset([
    "spoke", "talked", "asked", "told", "said", "replied", "mentioned",
    "learned", "revealed", "confessed", "heard", "questioned", "confronted",
    "greeted", "warned", "threatened", "persuaded", "deceived", "admitted",
    "showed", "gave", "traded", "accused", "denied",
])


def _is_movement_request(text: str) -> bool:
    lowered = " ".join(str(text or "").lower().split())
    return any(phrase in lowered for phrase in _MOVEMENT_PHRASES)


def _summary_has_interaction(summary: str) -> bool:
    lowered = " ".join(str(summary or "").lower().split())
    return any(word in lowered for word in _INTERACTION_WORDS)

class StoryEngine:

    def __init__(
        self,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
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

        resolved_provider = str(provider or get_default_provider()).strip().lower()
        resolved_model = model or get_default_model(resolved_provider)

        from ..app_config import get_provider_config
        from ..llm_interaction.providers.factory import create_provider

        provider_config = dict(get_provider_config(resolved_provider))
        if api_key:
            provider_config["api_key"] = api_key
        llm_provider = create_provider(resolved_provider, provider_config)

        self.adapter = LLMAdapter(
            model=resolved_model,
            provider=llm_provider,
            default_options=get_provider_default_options(resolved_provider),
            stage_options=get_provider_stage_options(resolved_provider),
            verbose=verbose,
        )

        self.steps = build_steps()
        self.snapshot_builder = SnapshotBuilder()

    # -----------------------

    def _make_state(self, player_input):
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

        state = self._make_state(player_input)

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
        # SINGLE AGENT LOOP
        # The model uses read/write world tools freely and ends the turn by
        # calling `finalize_turn`, which is a terminal tool whose payload
        # becomes the narration contract.
        # -----------------------

        turn_ctx: Dict[str, Any] = {
            "phase": "agent",
            "todo": [],
            "todo_revision": 0,
            "todo_summary": "",
            "notes": [],
            "all_world_tool_calls": [],
            "current_location": self.game_state.player_location,
            "finalize": None,
        }
        action_tool_calls: List[Dict[str, Any]] = []
        bind_turn_orchestration_ctx(self.game_state, turn_ctx)

        world_tools_by_name = {
            tool["function"]["name"]: tool
            for tool in TOOL_DEFINITIONS
            if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
        }

        agent_tool_defs: list[dict[str, Any]] = [
            *world_tools_by_name.values(),
            FINALIZE_TURN_TOOL_DEFINITION,
        ]
        agent_tool_names = {
            *world_tools_by_name.keys(),
            "finalize_turn",
        }

        # Trace keyed by tool name of calls that actually returned ok.
        successful_tool_calls: Dict[str, int] = {}

        def tool_executor(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
            args = dict(arguments or {})
            turn_ctx["current_location"] = self.game_state.player_location

            # Manual roll passthrough (UI-supplied d20) for skill_check / single-die roll_dice.
            manual_roll_supported = (
                tool_name == "skill_check"
                or (tool_name == "roll_dice" and int(args.get("count", 1) or 1) == 1)
            )
            if (
                manual_roll_supported
                and self.roll_mode == "manual"
                and callable(self.manual_roll_provider)
                and "_manual_roll" not in args
            ):
                args["_manual_roll"] = int(self.manual_roll_provider({
                    "tool_name": tool_name,
                    "phase": "agent",
                    "arguments": dict(args),
                }))

            result = execute_world_tool(tool_name, args, self.game_state)

            success = result.get("ok")
            if success is None:
                success = result.get("success", True)

            turn_ctx["all_world_tool_calls"].append({
                "phase": "agent",
                "name": tool_name,
                "arguments": args,
                "result": result,
            })

            if success:
                successful_tool_calls[tool_name] = successful_tool_calls.get(tool_name, 0) + 1

            if tool_name in {
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
            if tool_name not in agent_tool_names:
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
            # Give the model actionable feedback when a state-mutation call fails.
            if tool_name == "move_to_location":
                reason = str(payload.get("reason") or payload.get("error") or "unknown reason")
                return (
                    f"move_to_location failed: {reason}. "
                    "Set blocked_reason in finalize_turn to explain why movement was blocked."
                )
            if tool_name == "write_memory_tool":
                reason = str(payload.get("reason") or payload.get("error") or "unknown reason")
                return f"write_memory_tool failed: {reason}. Retry with valid entity_name and non-empty memory."
            if tool_name == "skill_check":
                reason = str(payload.get("reason") or payload.get("error") or "unknown reason")
                return f"skill_check failed: {reason}. Retry with valid entity_key and skill name."
            return None

        def response_hook(assistant_text: str, tool_calls: Sequence[Dict[str, Any]], _iteration: int) -> Optional[str]:
            text = str(assistant_text or "").strip()
            if len(tool_calls) > 1:
                return "Use at most one tool call per response."
            if not text:
                if tool_calls:
                    return None
                return "Every response must include a short `Decision Summary:` line."
            if not _extract_labeled_line(text, "Decision Summary"):
                return "Every response must begin with `Decision Summary: ...`."
            if (
                not tool_calls
                and _mentions_unresolved_roll_request(text)
                and turn_ctx.get("finalize") is None
            ):
                return "If a roll/check is needed, call `skill_check` now. Do not defer rolls to narration."
            return None

        def stop_hook(assistant_text: str, already_fired: bool) -> Optional[str]:
            """
            Gate loop termination on the actual tool trace.

            First stop attempt (already_fired=False): run one-shot world-state
            verification and push back with specific corrective instructions if
            any obligation was not fulfilled.

            After that (already_fired=True): allow completion unconditionally to
            prevent an infinite corrective loop.
            """
            if turn_ctx.get("finalize") is None:
                return (
                    "The turn is not finished. Call `finalize_turn` with a turn_summary "
                    "once you have resolved the player's action."
                )

            # Already pushed back once — trust the model's second attempt.
            if already_fired:
                return None

            finalize = turn_ctx["finalize"]
            issues: list[str] = []

            # ── Obligation 1: player movement ──────────────────────────────
            # If the player input reads as a movement request AND
            # move_to_location was never called AND no blocked_reason was set,
            # the world model still shows the old location. Require the call.
            if _is_movement_request(player_input):
                if not successful_tool_calls.get("move_to_location"):
                    if not str(finalize.get("blocked_reason", "")).strip():
                        issues.append(
                            "Player input is a movement request but `move_to_location` was not called "
                            "and no `blocked_reason` is set. "
                            "Call `move_to_location` now (the result tells you if it succeeded or why it failed), "
                            "then re-call `finalize_turn`."
                        )

            # ── Obligation 2: NPC interaction memory ───────────────────────
            # If the model queried NPC-specific tools AND the turn_summary
            # contains interaction words, significant facts were likely
            # established. Require at least one write_memory_tool call.
            npc_query_tools = {"get_entity_state", "check_can_interact", "retrieve_memory_tool"}
            if any(t in successful_tool_calls for t in npc_query_tools):
                if not successful_tool_calls.get("write_memory_tool"):
                    summary = finalize.get("turn_summary", "")
                    if _summary_has_interaction(summary):
                        issues.append(
                            "The turn involved NPC interaction (NPC query tools were called, "
                            "interaction recorded in turn_summary) but `write_memory_tool` was "
                            "never called. Persist the key fact now, then re-call `finalize_turn`."
                        )

            if issues:
                # Clear the finalize payload so the model must re-call finalize_turn
                # after it fixes the state. The `already_fired` flag prevents this
                # check from firing more than once.
                turn_ctx["finalize"] = None
                return (
                    "World state not fully updated — fix before finalizing:\n"
                    + "\n".join(f"• {issue}" for issue in issues)
                )

            return None

        agent_prompt = build_agent_prompt(state)

        agent_loop = self.adapter.run_tool_loop(
            stage="agent",
            system_prompt=AGENT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": agent_prompt}],
            tools=agent_tool_defs,
            tool_executor=tool_executor,
            max_iterations=16,
            pre_tool_use=pre_tool_use,
            post_tool_use=post_tool_use,
            assistant_response_hook=response_hook,
            stop_hook=stop_hook,
        )

        # Recover a finalize payload even if the model ran out of iterations.
        finalize_payload = turn_ctx.get("finalize") or {
            "turn_summary": f"Turn ended without an explicit finalize_turn call. Player action: {player_input}",
            "narration_focus": "",
            "blocked_reason": "Agent loop hit max iterations before finalizing.",
        }

        # Rebuild state with the updated game state for narration.
        if self.adapter.verbose:
            print("\n[STATE] Rebuilding state with updated game state")
            print(f"[STATE] Player location: {self.game_state.player_location}")

        state = self._make_state(player_input)

        if trace is not None:
            trace["STATE_AFTER_ACTION"] = build_state_snapshot()

        # -----------------------
        # NARRATE (consumes the contracted finalize payload)
        # -----------------------

        narrate_prompt = build_narrate_prompt(
            state,
            turn_summary=finalize_payload.get("turn_summary", ""),
            narration_focus=finalize_payload.get("narration_focus", ""),
            blocked_reason=finalize_payload.get("blocked_reason", ""),
            action_results=action_tool_calls,
        )

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
            "beat": self.beats.current(),
            "player_location": self.game_state.player_location,
            "scene": self.world.scene_snapshot(self.game_state.player_location),
            "tool_calls": action_tool_calls,
            "turn_todo": json.loads(json.dumps(turn_ctx["todo"])),
            "turn_summary": finalize_payload.get("turn_summary", ""),
            "narration_focus": finalize_payload.get("narration_focus", ""),
            "blocked_reason": finalize_payload.get("blocked_reason", ""),
        }

        if trace is not None:
            trace["AGENT"] = {
                "status": agent_loop.get("status"),
                "prompt": agent_prompt,
                "final_answer": agent_loop.get("final_answer", ""),
                "rounds": agent_loop.get("rounds", []),
                "finalize": finalize_payload,
                "successful_tool_counts": dict(successful_tool_calls),
            }
            trace["ACTION_TOOLS"] = action_tool_calls
            trace["WORLD_TOOLS"] = turn_ctx["all_world_tool_calls"]
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

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
from .reconciliation import build_runtime_state_snapshot, reconcile_turn
from .session_state import BeatTracker, SessionSummary, SnapshotBuilder
from .step_registry import build_steps
from ..llm_interaction.prompt_builders import (
    PromptState,
    build_agent_prompt,
    build_intro_prompt,
    build_narrate_prompt,
    build_phase_two_prompt,
)
from ..llm_interaction.prompt_texts import (
    PHASE_1_SYSTEM_PROMPT,
    PHASE_2_SYSTEM_PROMPT,
)
from ..world_state.story import create_initial_game_state
from ..world_state.tool_runtime import get_runtime_world_model
from ..world_state.world_model import WorldModel, build_world_model, resolve_world_model_data_dir
import json
import re
from ..world_state.tools import (
    FINALIZE_TURN_TOOL_DEFINITION,
    FINALIZE_WRITES_TOOL_DEFINITION,
    PHASE_1_TOOL_DEFINITIONS,
    PHASE_1_TOOL_NAMES,
    PHASE_2_TOOL_DEFINITIONS,
    PHASE_2_TOOL_NAMES,
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


def _turn_has_resolved_roll(turn_ctx: Dict[str, Any]) -> bool:
    """
    True when at least one roll has already fired during this turn, either
    through a direct skill_check call or through a tool that rolled
    Used to suppress the 'defer roll to narration' guard once a roll exists,
    so the model can legitimately reference the prior result in its Decision Summary
    without being blocked for using words like 'roll', 'DC', or 'check'.
    """
    for call in turn_ctx.get("all_world_tool_calls", []) or []:
        name = str(call.get("name") or "").strip()
        result = call.get("result") or {}
        if name == "skill_check" and (result.get("ok") or result.get("success")):
            return True
        if name == "check_can_interact":
            history = result.get("history_check") or {}
            if history.get("rolled"):
                return True
    return False


# Keywords that signal player movement intent.
_MOVEMENT_PHRASES = frozenset([
    "go to", "move to", "walk to", "run to", "travel to", "head to",
    "proceed to", "go back", "return to", "head back", "sneak to",
    "creep to", "rush to", "climb to", "go inside", "go outside",
    "enter the", "leave the", "exit the", "go through", "cross to",
    "explore", "visit",
])

# Keywords that signal significant NPC interaction in a turn summary.
_INTERACTION_WORDS = frozenset([
    "spoke", "talked", "asked", "told", "said", "replied", "mentioned",
    "learned", "revealed", "confessed", "heard", "questioned", "confronted",
    "greeted", "warned", "threatened", "persuaded", "deceived", "admitted",
    "showed", "gave", "traded", "accused", "denied", "discovered",
    "found", "noticed", "examined", "inspected", "investigated",
])

# Trivial player inputs that do not require a memory write.
_TRIVIAL_INPUT_PATTERNS = (
    re.compile(r"^\s*(hi|hello|hey|yo|sup|hiya)\s*[.!?]?\s*$", re.IGNORECASE),
    re.compile(r"^\s*(thanks|thank you|ty)\s*[.!?]?\s*$", re.IGNORECASE),
    re.compile(r"^\s*(ok|okay|alright|sure|yes|no|yep|nope)\s*[.!?]?\s*$", re.IGNORECASE),
    re.compile(r"^\s*(help|menu)\s*[.!?]?\s*$", re.IGNORECASE),
)


def _is_movement_request(text: str) -> bool:
    lowered = " ".join(str(text or "").lower().split())
    return any(phrase in lowered for phrase in _MOVEMENT_PHRASES)


def _summary_has_interaction(summary: str) -> bool:
    lowered = " ".join(str(summary or "").lower().split())
    return any(word in lowered for word in _INTERACTION_WORDS)


def _is_trivial_player_input(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return True
    return any(pattern.match(cleaned) for pattern in _TRIVIAL_INPUT_PATTERNS)


def _tool_call_succeeded(call: Dict[str, Any]) -> bool:
    result = call.get("result") or {}
    if "ok" in result:
        return bool(result.get("ok"))
    return bool(result.get("success", False))


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
        self.summary = SessionSummary(max_items=12, max_chars=2400)
        self.turn_index = 0
        self.story_status = ""
        self.last_turn_result: dict[str, Any] = {}

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
        self.game_state.visited_locations = {resolved_starting_location}
        # discovered_locations is derived (neighbors of visited minus visited),
        # so recompute right after the visited set changes.
        from ..world_state.story import recompute_discovered_locations
        recompute_discovered_locations(self.game_state, self.world)
        self.visited_locations = self.game_state.visited_locations
        self.discovered_locations = self.game_state.discovered_locations
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
                "visited": "yes" if location.key in self.game_state.visited_locations else "no",
                "discovered": "yes" if location.key in self.game_state.discovered_locations else "no",
            })

        for key in connected_locations:
            adjacent = self.world.get_location(key)
            if adjacent is None:
                continue
            entity_info[adjacent.key] = apply_relevant_flags(adjacent.key, {
                "node_type": "location",
                "connections": ", ".join(adjacent.connections) if adjacent.connections else "none",
                "location": adjacent.key,
                "visited": "yes" if adjacent.key in self.game_state.visited_locations else "no",
                "discovered": "yes" if adjacent.key in self.game_state.discovered_locations else "no",
            })

        player = self.world.get_entity("Player")
        if player is not None:
            player_info = {
                "node_type": player.entity_type,
                "location": player.location,
            }
            if player.inventory:
                player_info["inventory"] = ", ".join(player.inventory)
            entity_info[player.key] = apply_relevant_flags(player.key, player_info)

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
            history_text=self.history.as_text(limit=6),
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
            visited_locations=sorted(self.game_state.visited_locations),
            discovered_locations=sorted(self.game_state.discovered_locations),
        )

    # -----------------------

    def run_turn(self, player_input: str):

        trace: dict[str, Any] = {}

        state = self._make_state(player_input)
        world_before = build_runtime_state_snapshot(self)

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

        trace["PROMPT_STATE_BEFORE"] = json.loads(json.dumps(vars(state), ensure_ascii=True))
        trace["STATE_BEFORE"] = build_state_snapshot()

        # -----------------------
        # Shared turn orchestration context (used by both phases).
        # -----------------------

        turn_ctx: Dict[str, Any] = {
            "phase": "phase_one",
            "todo": [],
            "todo_revision": 0,
            "todo_summary": "",
            "notes": [],
            "all_world_tool_calls": [],
            "current_location": self.game_state.player_location,
            "finalize": None,
            "finalize_writes": None,
            "roll_mode": self.roll_mode,
            "manual_roll_provider": (
                self.manual_roll_provider if self.roll_mode == "manual" else None
            ),
        }
        action_tool_calls: List[Dict[str, Any]] = []
        bind_turn_orchestration_ctx(self.game_state, turn_ctx)

        successful_tool_calls: Dict[str, int] = {}

        # =====================================================
        # PHASE 1: Read-only action + mechanics loop.
        # =====================================================

        phase_one_tool_defs: list[dict[str, Any]] = [
            *PHASE_1_TOOL_DEFINITIONS,
            FINALIZE_TURN_TOOL_DEFINITION,
        ]
        phase_one_allowed_names = set(PHASE_1_TOOL_NAMES) | {"finalize_turn"}

        _PHASE_ONE_CACHEABLE_TOOLS = frozenset({
            "check_can_interact",
            "get_current_context",
            "list_scene_entities",
            "get_entity_state",
            "get_world_graph",
            "get_world_connections",
            "get_world_location_overview",
            "get_world_location_detail",
            "retrieve_memory_tool",
            "get_recent_skill_checks",
        })

        def _cache_signature(tool_name: str, args: Dict[str, Any]) -> str:
            # Strip internal-only kwargs that should not affect the cache key.
            cleaned = {
                key: value
                for key, value in (args or {}).items()
                if not str(key).startswith("_")
            }
            try:
                payload = json.dumps(cleaned, sort_keys=True, default=str)
            except Exception:
                payload = repr(sorted((args or {}).items()))
            return f"{tool_name}::{payload}"

        def phase_one_tool_executor(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
            args = dict(arguments or {})
            turn_ctx["current_location"] = self.game_state.player_location

            # Cache lookup: if the model is re-issuing a read
            # because of a validation rejection in the previous iteration,
            # serve the prior result instead of executing again. This is
            # what prevents check_can_interact from prompting for a second
            # History roll when the model just needed to add a Decision
            # Summary header to its text.
            cache: Dict[str, Dict[str, Any]] = turn_ctx.setdefault("phase_one_tool_cache", {})
            cache_key = _cache_signature(tool_name, args)
            if tool_name in _PHASE_ONE_CACHEABLE_TOOLS and cache_key in cache:
                cached_result = dict(cache[cache_key])
                cached_result["_cached"] = True
                turn_ctx["all_world_tool_calls"].append({
                    "phase": "phase_one",
                    "name": tool_name,
                    "arguments": args,
                    "result": cached_result,
                    "cached": True,
                })
                return cached_result

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
                    "phase": "phase_one",
                    "arguments": dict(args),
                }))

            result = execute_world_tool(tool_name, args, self.game_state)

            success = result.get("ok")
            if success is None:
                success = result.get("success", True)

            turn_ctx["all_world_tool_calls"].append({
                "phase": "phase_one",
                "name": tool_name,
                "arguments": args,
                "result": result,
            })

            # Store successful results from cacheable tools so duplicate
            # calls later in the turn return the same payload without
            # re-executing.
            if success and tool_name in _PHASE_ONE_CACHEABLE_TOOLS:
                cache[cache_key] = dict(result)

            if success:
                successful_tool_calls[tool_name] = successful_tool_calls.get(tool_name, 0) + 1

            if tool_name in {"roll_dice", "skill_check"}:
                action_tool_calls.append({
                    "phase": "phase_one",
                    "name": tool_name,
                    "arguments": args,
                    "result": result,
                })

            return result

        def phase_one_pre_tool_use(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
            _ = arguments
            if tool_name not in phase_one_allowed_names:
                return {
                    "allow": False,
                    "reason": (
                        f"Tool '{tool_name}' is not available in Phase 1. "
                        "Use only read tools, mechanics tools, and finalize_turn."
                    ),
                }
            # Block any second call to finalize_turn after a successful one.
            if tool_name == "finalize_turn" and turn_ctx.get("finalize") is not None:
                return {
                    "allow": False,
                    "reason": (
                        "finalize_turn was already called and succeeded. "
                        "STOP RESPONDING. Do not call finalize_turn again. "
                        "Do not call any more tools. The narrator will run automatically."
                    ),
                }
            return {"allow": True}

        def phase_one_post_tool_use(tool_name: str, arguments: Dict[str, Any], payload: Dict[str, Any]) -> Optional[str]:
            _ = arguments
            success = payload.get("ok")
            if success is None:
                success = payload.get("success", True)
            if success:
                return None
            error_text = str(payload.get("error") or payload.get("reason") or "").lower()
            if "unknown tool" in error_text:
                return f"Unknown tool `{tool_name}`. Use one of the provided tools."
            if tool_name == "skill_check":
                reason = str(payload.get("reason") or payload.get("error") or "unknown reason")
                return f"skill_check failed: {reason}. Retry with valid entity_key and skill name."
            return None

        def phase_one_response_hook(assistant_text: str, tool_calls: Sequence[Dict[str, Any]], _iteration: int) -> Optional[str]:
            text = str(assistant_text or "").strip()
            if len(tool_calls) > 1:
                return "Use at most one tool call per response."
            if not text:
                if tool_calls:
                    return None
                return "Every response must include a `Decision Summary:` line."
            if not _extract_labeled_line(text, "Decision Summary"):
                return "Every response must begin with `Decision Summary: ...`."
            # Catch the "tool call as text" failure mode: model wrote a tool
            # name in markdown but did not actually call it.
            if (
                not tool_calls
                and turn_ctx.get("finalize") is None
                and re.search(r"(?i)\b(tool|function)\s*:\s*finalize_turn\b", text)
            ):
                return (
                    "Detected `finalize_turn` written as text instead of called "
                    "as a tool. Issue a real function call to finalize_turn."
                )
            if (
                not tool_calls
                and _mentions_unresolved_roll_request(text)
                and turn_ctx.get("finalize") is None
                and not _turn_has_resolved_roll(turn_ctx)
            ):
                return "If a roll/check is needed, call `skill_check` now. Do not defer rolls to narration."
            return None

        def phase_one_stop_hook(assistant_text: str, already_fired: bool) -> Optional[str]:
            _ = assistant_text, already_fired
            if turn_ctx.get("finalize") is None:
                return (
                    "The phase is not finished. Call `finalize_turn` now "
                    "with this exact shape: "
                    '{"turn_summary": "<what happened this turn>", '
                    '"narration_focus": "<what the narrator should describe>", '
                    '"blocked_reason": ""}. '
                    "If something blocked the action, put the reason in "
                    "blocked_reason instead of leaving it empty. Do not "
                    "call any other tools first."
                )
            return None

        turn_ctx["phase"] = "phase_one"
        phase_one_prompt = build_agent_prompt(state)

        phase_one_loop = self.adapter.run_tool_loop(
            stage="phase_one",
            system_prompt=PHASE_1_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": phase_one_prompt}],
            tools=phase_one_tool_defs,
            tool_executor=phase_one_tool_executor,
            max_iterations=16,
            pre_tool_use=phase_one_pre_tool_use,
            post_tool_use=phase_one_post_tool_use,
            assistant_response_hook=phase_one_response_hook,
            stop_hook=phase_one_stop_hook,
            early_exit=lambda: turn_ctx.get("finalize") is not None,
        )

        finalize_payload = turn_ctx.get("finalize") or {
            "turn_summary": f"Turn ended without an explicit finalize_turn call. Player action: {player_input}",
            "narration_focus": "",
            "blocked_reason": "Phase 1 hit max iterations before finalizing.",
        }

        # =====================================================
        # NARRATION (against pre-write state)
        # =====================================================

        phase_one_tool_calls = [
            c for c in turn_ctx["all_world_tool_calls"] if c.get("phase") == "phase_one"
        ]

        narrate_prompt = build_narrate_prompt(
            state,
            turn_summary=finalize_payload.get("turn_summary", ""),
            narration_focus=finalize_payload.get("narration_focus", ""),
            blocked_reason=finalize_payload.get("blocked_reason", ""),
            action_results=action_tool_calls,
            phase_one_tool_calls=phase_one_tool_calls,
        )

        if self.adapter.verbose:
            print("\n[NARRATE] Generating narrative (pre-write state)")

        narrative, narrate_debug = self.steps["narrate"].run(
            self.adapter,
            narrate_prompt,
        )

        # =====================================================
        # PHASE 2: Writer loop.
        # =====================================================

        phase_two_tool_defs: list[dict[str, Any]] = [
            *PHASE_2_TOOL_DEFINITIONS,
            FINALIZE_WRITES_TOOL_DEFINITION,
        ]
        phase_two_allowed_names = set(PHASE_2_TOOL_NAMES) | {"finalize_writes"}

        def phase_two_tool_executor(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
            args = dict(arguments or {})
            result = execute_world_tool(tool_name, args, self.game_state)

            success = result.get("ok")
            if success is None:
                success = result.get("success", True)

            turn_ctx["all_world_tool_calls"].append({
                "phase": "phase_two",
                "name": tool_name,
                "arguments": args,
                "result": result,
            })

            if success:
                successful_tool_calls[tool_name] = successful_tool_calls.get(tool_name, 0) + 1

            if tool_name in {"move_to_location", "move_npc", "write_memory_tool"}:
                action_tool_calls.append({
                    "phase": "phase_two",
                    "name": tool_name,
                    "arguments": args,
                    "result": result,
                })

            if tool_name in {"move_to_location", "move_npc"} and success:
                turn_ctx["current_location"] = self.game_state.player_location

            return result

        def phase_two_pre_tool_use(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
            _ = arguments
            if tool_name not in phase_two_allowed_names:
                return {
                    "allow": False,
                    "reason": (
                        f"Tool '{tool_name}' is not available in Phase 2. "
                        "Use only move_to_location, move_npc, write_memory_tool, "
                        "or finalize_writes."
                    ),
                }
            # Block duplicate finalize_writes calls.
            if tool_name == "finalize_writes" and turn_ctx.get("finalize_writes") is not None:
                return {
                    "allow": False,
                    "reason": (
                        "finalize_writes was already called and succeeded. "
                        "STOP RESPONDING. Do not call finalize_writes again. "
                        "Do not call any more tools."
                    ),
                }
            return {"allow": True}

        def phase_two_post_tool_use(tool_name: str, arguments: Dict[str, Any], payload: Dict[str, Any]) -> Optional[str]:
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
            return None

        def phase_two_response_hook(assistant_text: str, tool_calls: Sequence[Dict[str, Any]], _iteration: int) -> Optional[str]:
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
                and turn_ctx.get("finalize_writes") is None
                and re.search(r"(?i)\b(tool|function)\s*:\s*(move_to_location|write_memory_tool|finalize_writes|move_npc)\b", text)
            ):
                return (
                    "Detected a tool name written as text instead of called "
                    "as a tool. Issue a real function call."
                )
            return None

        def phase_two_stop_hook(assistant_text: str, already_fired: bool) -> Optional[str]:
            _ = assistant_text
            if turn_ctx.get("finalize_writes") is None:
                return (
                    "The writer phase is not finished. Call `finalize_writes` "
                    "now with this shape: "
                    '{"writes_summary": "<short summary of writes applied>"}. '
                    "Do not call any other tools first."
                )
            if already_fired:
                return None

            issues: list[str] = []

            # Movement enforcement: if the player requested movement and it wasn't
            # blocked, Phase 2 should have called move_to_location.
            move_called_in_phase_two = any(
                call.get("phase") == "phase_two"
                and call.get("name") == "move_to_location"
                and _tool_call_succeeded(call)
                for call in turn_ctx["all_world_tool_calls"]
            )
            if _is_movement_request(player_input) and not move_called_in_phase_two:
                if not str(finalize_payload.get("blocked_reason", "")).strip():
                    issues.append(
                        "Player movement was requested but `move_to_location` "
                        "was not called in this phase. Call it now, then re-call finalize_writes."
                    )

            # Memory write enforcement: required on every turn except trivial ones.
            memory_written_in_phase_two = any(
                call.get("phase") == "phase_two"
                and call.get("name") == "write_memory_tool"
                and _tool_call_succeeded(call)
                for call in turn_ctx["all_world_tool_calls"]
            )
            if not memory_written_in_phase_two and not _is_trivial_player_input(player_input):
                issues.append(
                    "No memory was written this turn. Call `write_memory_tool` with "
                    "entity_name=\"Player\" and a brief memory describing what the "
                    "player did, learned, or experienced. If an NPC was involved, "
                    "also write a memory from that NPC's perspective. Then re-call "
                    "finalize_writes."
                )

            if issues:
                turn_ctx["finalize_writes"] = None
                return (
                    "Writes incomplete - fix before finalizing:\n"
                    + "\n".join(f"- {issue}" for issue in issues)
                )

            return None

        turn_ctx["phase"] = "phase_two"
        phase_two_prompt = build_phase_two_prompt(
            state,
            turn_summary=finalize_payload.get("turn_summary", ""),
            narration_focus=finalize_payload.get("narration_focus", ""),
            blocked_reason=finalize_payload.get("blocked_reason", ""),
            phase_one_tool_calls=phase_one_tool_calls,
            narration=narrative,
            action_results=action_tool_calls,
            world_before=world_before,
        )

        if self.adapter.verbose:
            print("\n[PHASE_TWO] Running writer phase")

        phase_two_loop = self.adapter.run_tool_loop(
            stage="phase_two",
            system_prompt=PHASE_2_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": phase_two_prompt}],
            tools=phase_two_tool_defs,
            tool_executor=phase_two_tool_executor,
            max_iterations=10,
            pre_tool_use=phase_two_pre_tool_use,
            post_tool_use=phase_two_post_tool_use,
            assistant_response_hook=phase_two_response_hook,
            stop_hook=phase_two_stop_hook,
            early_exit=lambda: turn_ctx.get("finalize_writes") is not None,
        )

        finalize_writes_payload = turn_ctx.get("finalize_writes") or {"writes_summary": ""}

        # =====================================================
        # RECONCILIATION
        # =====================================================

        next_turn_number = self.turn_index + 1
        reconciliation = reconcile_turn(
            self,
            turn_number=next_turn_number,
            player_input=player_input,
            turn_summary=finalize_payload.get("turn_summary", ""),
            blocked_reason=finalize_payload.get("blocked_reason", ""),
            narration=narrative,
            action_results=action_tool_calls,
            world_before=world_before,
        )

        # =====================================================
        # COMMIT TURN
        # =====================================================

        self.history.add_player_turn(player_input)
        self.history.add_dm_turn(narrative)
        self.turn_index = next_turn_number

        state = self._make_state(player_input)

        result = {
            "turn": self.turn_index,
            "narration": {"ic": narrative},
            "beat": self.beats.current(),
            "player_location": self.game_state.player_location,
            "scene": self.world.scene_snapshot(self.game_state.player_location),
            "tool_calls": action_tool_calls,
            "world_tool_calls": json.loads(json.dumps(turn_ctx["all_world_tool_calls"], ensure_ascii=True)),
            "turn_todo": json.loads(json.dumps(turn_ctx["todo"])),
            "turn_summary": finalize_payload.get("turn_summary", ""),
            "narration_focus": finalize_payload.get("narration_focus", ""),
            "blocked_reason": finalize_payload.get("blocked_reason", ""),
            "writes_summary": finalize_writes_payload.get("writes_summary", ""),
            "phase_summaries": {
                "phase_one": finalize_payload.get("turn_summary", ""),
                "narration": _summary_snippet(narrative),
                "phase_two": finalize_writes_payload.get("writes_summary", ""),
                "reconciliation": reconciliation.get("story_status", ""),
            },
            "reconciliation": reconciliation,
        }

        trace["PHASE_ONE"] = {
            "status": phase_one_loop.get("status"),
            "prompt": phase_one_prompt,
            "final_answer": phase_one_loop.get("final_answer", ""),
            "rounds": phase_one_loop.get("rounds", []),
            "messages": phase_one_loop.get("messages", []),
            "tool_calls": phase_one_loop.get("tool_calls", []),
            "finalize": finalize_payload,
        }
        trace["NARRATE"] = {
            "prompt": narrate_prompt,
            **narrate_debug,
        }
        trace["PHASE_TWO"] = {
            "status": phase_two_loop.get("status"),
            "prompt": phase_two_prompt,
            "final_answer": phase_two_loop.get("final_answer", ""),
            "rounds": phase_two_loop.get("rounds", []),
            "messages": phase_two_loop.get("messages", []),
            "tool_calls": phase_two_loop.get("tool_calls", []),
            "finalize_writes": finalize_writes_payload,
        }
        trace["ACTION_TOOLS"] = action_tool_calls
        trace["WORLD_TOOLS"] = turn_ctx["all_world_tool_calls"]
        trace["MOVEMENT_BLOCKED"] = (
            any(
                call.get("name") == "move_to_location"
                and call.get("phase") == "phase_two"
                and not _tool_call_succeeded(call)
                for call in turn_ctx["all_world_tool_calls"]
            )
            and self.game_state.player_location == world_before.get("player_location", "")
        )
        trace["SUCCESSFUL_TOOL_COUNTS"] = dict(successful_tool_calls)
        trace["RECONCILIATION"] = reconciliation
        trace["PROMPT_STATE_AFTER_RECONCILE"] = json.loads(json.dumps(vars(state), ensure_ascii=True))
        trace["STATE_AFTER"] = build_state_snapshot()
        result["llm_trace"] = trace

        self.last_turn_result = json.loads(json.dumps(result, ensure_ascii=True))

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

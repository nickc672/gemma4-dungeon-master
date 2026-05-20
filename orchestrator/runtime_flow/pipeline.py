from __future__ import annotations
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
from .state_builder import PromptStateBuilder, build_trace_state_snapshot
from .step_registry import build_steps
from .turn_context import TurnContext
from .turn_heuristics import _summary_snippet
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
from ..world_state.tool_runtime import find_world_object, get_runtime_world_model
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

from .phases import (
    Phase1Runner,
    PhaseOneInput,
    NarrationRunner,
    NarrationInput,
    Phase2Runner,
    PhaseTwoInput,
)


"""
Turn flow:
    1. Build PromptState and capture world_before snapshot.
    2. Create a fresh TurnContext and bind it to game_state.
    3. Phase 1 -> read + mechanics tool loop, ends with finalize_turn.
    4. Narration -> single LLM step against pre-write world state.
    5. Phase 2 -> writer tool loop, ends with finalize_writes.
    6. Reconciliation -> diff world_before / world_after, derive flags.
    7. Commit -> append to history, advance turn index, return result dict.
"""

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
        self.state_builder = PromptStateBuilder()

    # -----------------------
    # Phase runners
    # -----------------------
        self.phase_one = Phase1Runner(
            adapter=self.adapter,
            execute_world_tool=execute_world_tool,
            find_world_object=find_world_object,
            tool_defs=PHASE_1_TOOL_DEFINITIONS,
            tool_names=PHASE_1_TOOL_NAMES,
            finalize_tool_def=FINALIZE_TURN_TOOL_DEFINITION,
            system_prompt=PHASE_1_SYSTEM_PROMPT,
            prompt_builder=build_agent_prompt,
        )
        self.narration = NarrationRunner(
            adapter=self.adapter,
            narrate_step=self.steps["narrate"],
            prompt_builder=build_narrate_prompt,
        )
        self.phase_two = Phase2Runner(
            adapter=self.adapter,
            execute_world_tool=execute_world_tool,
            find_world_object=find_world_object,
            tool_defs=PHASE_2_TOOL_DEFINITIONS,
            tool_names=PHASE_2_TOOL_NAMES,
            finalize_tool_def=FINALIZE_WRITES_TOOL_DEFINITION,
            system_prompt=PHASE_2_SYSTEM_PROMPT,
            prompt_builder=build_phase_two_prompt,
        )

    # -----------------------
    # builds the prompt state from current engine state.
    # -----------------------
    def _make_state(self, player_input: str) -> PromptState:
        return self.state_builder.build(self, player_input)

    # =====================================================
    # Turn orchestration
    # =====================================================
    def run_turn(self, player_input: str) -> Dict[str, Any]:
        trace: dict[str, Any] = {}

        state = self._make_state(player_input)
        world_before = build_runtime_state_snapshot(self)

        trace["PROMPT_STATE_BEFORE"] = json.loads(json.dumps(vars(state), ensure_ascii=True))
        trace["STATE_BEFORE"] = build_trace_state_snapshot(self, state)

        turn_ctx = TurnContext.fresh(
            current_location=self.game_state.player_location,
            roll_mode=self.roll_mode,
            manual_roll_provider=self.manual_roll_provider,
        )
        bind_turn_orchestration_ctx(self.game_state, turn_ctx.as_dict())

        try:
        # =====================================================
        # PHASE 1: Read-only action + mechanics loop.
        # =====================================================
            phase_one_output = self.phase_one.run(PhaseOneInput(
                state=state,
                player_input=player_input,
                turn_ctx=turn_ctx,
                game_state=self.game_state,
                roll_mode=self.roll_mode,
                manual_roll_provider=self.manual_roll_provider,
            ))

        # =====================================================
        # NARRATION (against pre-write state)
        # =====================================================
            narration_output = self.narration.run(NarrationInput(
                state=state,
                turn_summary=phase_one_output.finalize_payload.get("turn_summary", ""),
                narration_focus=phase_one_output.finalize_payload.get("narration_focus", ""),
                blocked_reason=phase_one_output.finalize_payload.get("blocked_reason", ""),
                action_tool_calls=phase_one_output.action_tool_calls,
                phase_one_tool_calls=phase_one_output.phase_one_tool_calls,
            ))

        # =====================================================
        # PHASE 2: Writer loop.
        # =====================================================
            phase_two_output = self.phase_two.run(PhaseTwoInput(
                state=state,
                player_input=player_input,
                turn_ctx=turn_ctx,
                game_state=self.game_state,
                finalize_payload=phase_one_output.finalize_payload,
                phase_one_tool_calls=phase_one_output.phase_one_tool_calls,
                narration=narration_output.narrative,
                action_tool_calls=phase_one_output.action_tool_calls,
                world_before=world_before,
            ))

        # =====================================================
        # RECONCILIATION
        # =====================================================
            next_turn_number = self.turn_index + 1
            combined_action_tool_calls = (
                list(phase_one_output.action_tool_calls)
                + list(phase_two_output.action_tool_calls)
            )
            reconciliation = reconcile_turn(
                self,
                turn_number=next_turn_number,
                player_input=player_input,
                turn_summary=phase_one_output.finalize_payload.get("turn_summary", ""),
                blocked_reason=phase_one_output.finalize_payload.get("blocked_reason", ""),
                narration=narration_output.narrative,
                action_results=combined_action_tool_calls,
                world_before=world_before,
            )

        # =====================================================
        # COMMIT TURN
        # =====================================================
            self.history.add_player_turn(player_input)
            self.history.add_dm_turn(narration_output.narrative)
            self.turn_index = next_turn_number

            state_after = self._make_state(player_input)

            successful_tool_counts: Dict[str, int] = {}
            for source in (phase_one_output.successful_tool_counts, phase_two_output.successful_tool_counts):
                for name, count in source.items():
                    successful_tool_counts[name] = successful_tool_counts.get(name, 0) + count

            result = {
                "turn": self.turn_index,
                "narration": {"ic": narration_output.narrative},
                "beat": self.beats.current(),
                "player_location": self.game_state.player_location,
                "scene": self.world.scene_snapshot(self.game_state.player_location),
                "tool_calls": combined_action_tool_calls,
                "world_tool_calls": json.loads(
                    json.dumps(turn_ctx.all_world_tool_calls, ensure_ascii=True)
                ),
                "turn_todo": json.loads(json.dumps(turn_ctx.todo)),
                "turn_summary": phase_one_output.finalize_payload.get("turn_summary", ""),
                "narration_focus": phase_one_output.finalize_payload.get("narration_focus", ""),
                "blocked_reason": phase_one_output.finalize_payload.get("blocked_reason", ""),
                "writes_summary": phase_two_output.finalize_writes_payload.get("writes_summary", ""),
                "unresolved_interaction_targets": list(turn_ctx.unresolved_interaction_targets),
                "entities_created": reconciliation.get("entities_created", []),
                "items_created": reconciliation.get("items_created", []),
                "phase_summaries": {
                    "phase_one": phase_one_output.finalize_payload.get("turn_summary", ""),
                    "narration": _summary_snippet(narration_output.narrative),
                    "phase_two": phase_two_output.finalize_writes_payload.get("writes_summary", ""),
                    "reconciliation": reconciliation.get("story_status", ""),
                },
                "reconciliation": reconciliation,
            }

        # =====================================================
        # TRACE
        # =====================================================
            trace["PHASE_ONE"] = {
                "status": phase_one_output.loop_result.get("status"),
                "prompt": phase_one_output.prompt,
                "final_answer": phase_one_output.loop_result.get("final_answer", ""),
                "rounds": phase_one_output.loop_result.get("rounds", []),
                "messages": phase_one_output.loop_result.get("messages", []),
                "tool_calls": phase_one_output.loop_result.get("tool_calls", []),
                "finalize": phase_one_output.finalize_payload,
            }
            trace["NARRATE"] = {
                "prompt": narration_output.prompt,
                **narration_output.debug,
            }
            trace["PHASE_TWO"] = {
                "status": phase_two_output.loop_result.get("status"),
                "prompt": phase_two_output.prompt,
                "final_answer": phase_two_output.loop_result.get("final_answer", ""),
                "rounds": phase_two_output.loop_result.get("rounds", []),
                "messages": phase_two_output.loop_result.get("messages", []),
                "tool_calls": phase_two_output.loop_result.get("tool_calls", []),
                "finalize_writes": phase_two_output.finalize_writes_payload,
            }
            trace["ACTION_TOOLS"] = combined_action_tool_calls
            trace["WORLD_TOOLS"] = list(turn_ctx.all_world_tool_calls)
            trace["MOVEMENT_BLOCKED"] = self._movement_blocked(turn_ctx, world_before)
            trace["SUCCESSFUL_TOOL_COUNTS"] = dict(successful_tool_counts)
            trace["RECONCILIATION"] = reconciliation
            trace["PROMPT_STATE_AFTER_RECONCILE"] = json.loads(
                json.dumps(vars(state_after), ensure_ascii=True)
            )
            trace["STATE_AFTER"] = build_trace_state_snapshot(self, state_after)
            result["llm_trace"] = trace

            self.last_turn_result = json.loads(json.dumps(result, ensure_ascii=True))
            return result
        finally:
            clear_turn_orchestration_ctx(self.game_state)

    def _movement_blocked(self, turn_ctx: TurnContext, world_before: Dict[str, Any]) -> bool:
        """True when a Phase 2 move_to_location call failed and the player did not move."""
        from .turn_heuristics import _tool_call_succeeded
        any_failed_move = any(
            call.get("name") == "move_to_location"
            and call.get("phase") == "phase_two"
            and not _tool_call_succeeded(call)
            for call in turn_ctx.all_world_tool_calls
        )
        return any_failed_move and self.game_state.player_location == world_before.get("player_location", "")

    # =====================================================
    # Intro generation
    # =====================================================
    def generate_intro(self):
        intro_scene = self.world.scene_snapshot(self.game_state.player_location)

        intro_location = self.world.get_location(self.game_state.player_location)
        intro_location_memory: list[str] = []
        if intro_location is not None:
            intro_location_memory = [
                str(line).strip()
                for line in list(intro_location.memory.sentences)
                if str(line).strip()
            ]

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
            location_memory=intro_location_memory,
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


__all__ = ["StoryEngine"]
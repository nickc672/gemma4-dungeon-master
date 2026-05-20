from __future__ import annotations
from typing import Any, Dict, List, Tuple
from ..turn_heuristics import _is_movement_request, _is_trivial_player_input, _tool_call_succeeded
from ..turn_context import TurnContext

"""
validator functions for the finalize stop-hooks.
These were inline blocks inside the Phase 1 and Phase 2 stop_hook closures.
"""

def compute_missing_memory_retrievals(
    *,
    turn_ctx: TurnContext,
    state: Any,
    player_input: str,
    game_state: Any,
    finalize_payload: Dict[str, Any],
    find_world_object,
) -> Tuple[List[str], List[str]]:
    """
    Return (missing_npcs, missing_locations): scene NPCs the player addressed
    and movement destinations that have memories on file but were not retrieved during Phase 1.
    """
    turn_summary_text = str(finalize_payload.get("turn_summary") or "")
    narration_focus_text = str(finalize_payload.get("narration_focus") or "")
    search_text = " ".join([
        str(player_input or ""),
        turn_summary_text,
        narration_focus_text,
    ]).lower()

    retrieved_keys: set[str] = set()
    for call in turn_ctx.all_world_tool_calls:
        if call.get("phase") != "phase_one":
            continue
        if call.get("name") != "retrieve_memory_tool":
            continue
        if not _tool_call_succeeded(call):
            continue
        args = call.get("arguments") or {}
        name = str(args.get("entity_name") or "").strip()
        if not name:
            continue
        obj = find_world_object(name, game_state)
        if obj is not None:
            retrieved_keys.add(obj.key)

    missing_npcs: List[str] = []
    missing_locations: List[str] = []

    for actor_name in state.scene_actors or []:
        name_str = str(actor_name or "").strip()
        if not name_str:
            continue
        if name_str.lower() not in search_text:
            continue
        npc = find_world_object(name_str, game_state)
        if npc is None:
            continue
        if getattr(npc, "entity_type", "") != "npc":
            continue
        if getattr(npc, "memory_count", 0) <= 0:
            continue
        if npc.key in retrieved_keys:
            continue
        if npc.name not in missing_npcs:
            missing_npcs.append(npc.name)

    if _is_movement_request(player_input):
        current_loc_key = str(game_state.player_location or "").strip()
        for call in turn_ctx.all_world_tool_calls:
            if call.get("phase") != "phase_one":
                continue
            if call.get("name") != "check_can_interact":
                continue
            if not _tool_call_succeeded(call):
                continue
            result = call.get("result") or {}
            if not result.get("can_interact"):
                continue
            if str(result.get("entity_type") or "").lower() != "location":
                continue
            args = call.get("arguments") or {}
            target = str(args.get("entity_key") or "").strip()
            if not target:
                continue
            loc = find_world_object(target, game_state)
            if loc is None:
                continue
            if getattr(loc, "entity_type", "") != "location":
                continue
            if loc.key == current_loc_key:
                continue
            if getattr(loc, "memory_count", 0) <= 0:
                continue
            if loc.key in retrieved_keys:
                continue
            if loc.name not in missing_locations:
                missing_locations.append(loc.name)

    return missing_npcs, missing_locations


def format_memory_retrieval_nudge(missing_npcs: List[str], missing_locations: List[str]) -> str:
    """Format the soft-reminder text used by the Phase 1 stop hook."""
    nudge_lines: List[str] = [
        "Soft reminder: relevant stored memory was not retrieved this "
        "turn. Consider calling `retrieve_memory_tool` before "
        "finalizing so the narrator can voice NPCs and describe "
        "locations with continuity. Phase 2 does not retrieve memory; "
        "if it is not surfaced here it will not reach the narration."
    ]
    if missing_npcs:
        npc_list = ", ".join(missing_npcs)
        nudge_lines.append(
            "- NPC(s) the player addressed who have stored memories: "
            f"{npc_list}"
        )
    if missing_locations:
        loc_list = ", ".join(missing_locations)
        nudge_lines.append(
            "- Location(s) the player is moving to that have stored "
            f"memories: {loc_list}"
        )
    nudge_lines.append(
        "If you call retrieve_memory_tool, re-issue finalize_turn "
        "afterward. If you choose to proceed without retrieving, "
        "re-issue finalize_turn unchanged and the turn will continue."
    )
    return "\n".join(nudge_lines)


def compute_phase_two_writes_issues(
    *,
    turn_ctx: TurnContext,
    player_input: str,
    finalize_payload: Dict[str, Any],
    game_state: Any,
    find_world_object,
) -> List[str]:
    """
    Return a list of issue strings the model must address before
    finalize_writes is accepted. Empty list means the writes are complete.
    """
    issues: List[str] = []

    # Movement enforcement: if the player requested movement and it was not blocked, Phase 2 should have called move_to_location.
    move_called_in_phase_two = any(
        call.get("phase") == "phase_two"
        and call.get("name") == "move_to_location"
        and _tool_call_succeeded(call)
        for call in turn_ctx.all_world_tool_calls
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
        for call in turn_ctx.all_world_tool_calls
    )
    if not memory_written_in_phase_two and not _is_trivial_player_input(player_input):
        issues.append(
            "No memory was written this turn. Call `write_memory_tool` with "
            "entity_name=\"Player\" and a brief memory describing what the "
            "player did, learned, or experienced. If an NPC was involved, "
            "also write a memory from that NPC's perspective. Then re-call "
            "finalize_writes."
        )

    # Location memory enforcement: if move_to_location succeeded this turn, the destination location should also receive a memory write.
    successful_move_destinations: List[str] = []
    for call in turn_ctx.all_world_tool_calls:
        if call.get("phase") != "phase_two":
            continue
        if call.get("name") != "move_to_location":
            continue
        if not _tool_call_succeeded(call):
            continue
        result = call.get("result") or {}
        destination = str(result.get("new_location") or "").strip()
        if destination:
            successful_move_destinations.append(destination)

    if successful_move_destinations:
        location_memory_targets: set[str] = set()
        for call in turn_ctx.all_world_tool_calls:
            if call.get("phase") != "phase_two":
                continue
            if call.get("name") != "write_memory_tool":
                continue
            if not _tool_call_succeeded(call):
                continue
            args = call.get("arguments") or {}
            name = str(args.get("entity_name") or "").strip()
            if not name:
                continue
            obj = find_world_object(name, game_state)
            if obj is None:
                continue
            if getattr(obj, "entity_type", "") == "location":
                location_memory_targets.add(obj.key)

        missing_location_memories = [
            dest for dest in successful_move_destinations
            if dest not in location_memory_targets
        ]
        if missing_location_memories:
            dest_list = ", ".join(missing_location_memories)
            issues.append(
                "Player arrived at a new location but no memory was written "
                "on that location. Call `write_memory_tool` with "
                f"entity_name set to the destination ({dest_list}) and a "
                "brief third-person memory describing the arrival from the "
                "location's perspective. Then re-call finalize_writes."
            )

    return issues


__all__ = [
    "compute_missing_memory_retrievals",
    "format_memory_retrieval_nudge",
    "compute_phase_two_writes_issues",
]
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List

@dataclass
class PhaseTwoCase:
    id: str
    description: str
    player_input: str

    # Game state setup (initial state, before Phase 2 mutates anything)
    player_location: str
    npc_locations: Dict[str, str] = field(default_factory=dict)
    quest_flags: Dict[str, bool] = field(default_factory=dict)
    discovered_keys: List[str] = field(default_factory=list)
    visited_keys: List[str] = field(default_factory=list)
    conversation_history: List[str] = field(default_factory=list)
    story_status: str = ""

    # inputs from Phase 1 + Narration
    turn_summary: str = ""
    narration_focus: str = ""
    blocked_reason: str = ""
    narration: str = ""
    phase_one_tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    action_tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    # Tool-call expectations (closed-world; finalize_writes is implicit)
    expect_finalize_writes: bool = True
    expected_tools_called: List[Any] = field(default_factory=list)
    expected_writes_summary_keywords: List[List[str]] = field(default_factory=list)
    max_iterations: int = 0

    # State-change expectations
    
    # Player location is treated as expected to be `expected_location_after`
    # after the turn (which may equal `player_location` meaning "no change").
    
    # The other dict/list fields specify expected mutations. Anything not
    # listed here is considered an unexpected state change (false positive).
    expected_location_after: str = ""
    # NPC name -> expected location after the turn. Entries not listed are
    # expected to remain at their starting position from npc_locations.
    expected_npc_locations_after: Dict[str, str] = field(default_factory=dict)
    # Quest flag name -> expected value after the turn. Entries not listed
    # are expected to remain at their starting value.
    expected_quest_flags_after: Dict[str, bool] = field(default_factory=dict)
    # Location keys expected to be newly added to the visited set this turn.
    expected_visited_added: List[str] = field(default_factory=list)
    # Location keys expected to be newly added to the discovered set this turn.
    expected_discovered_added: List[str] = field(default_factory=list)
    # Entity names expected to have at least one memory line written this turn.
    expected_memory_writes: List[str] = field(default_factory=list)

    tags: List[str] = field(default_factory=list)


PHASE_TWO_CASES: List[PhaseTwoCase] = [
    PhaseTwoCase(
        id="P2-01",
        description="Standard movement: should call move_to_location and write memories",
        player_input="I want to go to the Copper Cup",
        player_location="Town Square",
        turn_summary="Player walked from Town Square to the Copper Cup.",
        narration_focus="Arrival at the Copper Cup.",
        blocked_reason="",
        narration=(
            "Thoughts: The player moves on, leaving the bustle of the square behind.\n"
            "Narrative: You push through the heavy door of the Copper Cup. "
            "The warm light and smell of malt wraps around you as you step inside."
        ),
        phase_one_tool_calls=[
            {"phase": "phase_one", "name": "check_can_interact",
             "arguments": {"entity_key": "Copper Cup"},
             "result": {"ok": True, "can_interact": True, "entity_type": "location"}},
        ],
        expect_finalize_writes=True,
        expected_tools_called=["move_to_location", "write_memory_tool"],
        expected_location_after="Copper Cup",
        expected_visited_added=["Copper Cup"],
        expected_discovered_added=["Back Door - Copper Cup", "Bar Counter", "Stair Landing"],
        expected_memory_writes=["Copper Cup", "Player"],
        tags=["movement", "easy"],
    ),
    PhaseTwoCase(
        id="P2-02",
        description="Conversation: should write memories for both participants",
        player_input="I ask Mara about the bloodstains",
        player_location="Copper Cup",
        npc_locations={"Mara": "Copper Cup"},
        turn_summary="Player asked Mara about the bloodstains. Mara mentioned a brawl.",
        narration_focus="Mara's reluctant answer.",
        blocked_reason="",
        narration=(
            "Thoughts: Mara hesitates; she does not want to talk about it.\n"
            "Narrative: Mara stops polishing the cup. \"There was a fight last night,\" "
            "she says, eyes flicking to the door. \"That is all I will say.\""
        ),
        phase_one_tool_calls=[
            {"phase": "phase_one", "name": "retrieve_memory_tool",
             "arguments": {"entity_name": "Mara"},
             "result": {"ok": True, "memories": ["Mara was upset about a brawl last night."]}},
        ],
        expect_finalize_writes=True,
        expected_tools_called=["write_memory_tool"],
        expected_location_after="Copper Cup",
        expected_memory_writes=["Mara", "Copper Cup", "Player"],
        tags=["social", "memory", "easy"],
    ),
    PhaseTwoCase(
        id="P2-03",
        description="Blocked action: should NOT move, but should still write a memory",
        player_input="I head straight to the temple",
        player_location="Copper Cup",
        turn_summary="Player tried to move directly to the temple; not reachable from here.",
        narration_focus="The path constraint surfaced through scene cues.",
        blocked_reason="The temple is not directly reachable from the Copper Cup.",
        narration=(
            "Thoughts: A direct path is not possible from this room.\n"
            "Narrative: You glance toward the door, but the temple lies on the far side "
            "of the square. You will need to step outside first."
        ),
        expect_finalize_writes=True,
        expected_tools_called=["write_memory_tool"],
        expected_location_after="Copper Cup",
        expected_memory_writes=["Player"],
        tags=["blocked", "medium"],
    ),
    PhaseTwoCase(
        id="P2-04",
        description="Successful stealth: should write memory referencing the outcome",
        player_input="I try to sneak past the guards",
        player_location="Harbor Gate",
        npc_locations={"Gate Guard Ren": "Harbor Gate"},
        turn_summary="Player slipped past Gate Guard Ren unseen with a stealth roll of 17 vs DC 14.",
        narration_focus="Tension, quiet steps, success.",
        blocked_reason="",
        narration=(
            "Thoughts: The guard's attention is elsewhere; this is the moment.\n"
            "Narrative: You ease past the lantern's edge of light. Ren's gaze drifts "
            "across the cobbles, never quite finding you."
        ),
        action_tool_calls=[
            {"phase": "phase_one", "name": "skill_check",
             "arguments": {"entity_key": "Player", "skill": "stealth", "dc": 14},
             "result": {"ok": True, "success": True, "roll": 17, "total": 17, "dc": 14}},
        ],
        expect_finalize_writes=True,
        expected_tools_called=["write_memory_tool"],
        expected_location_after="Harbor Gate",
        expected_memory_writes=["Player"],
        tags=["mechanics", "memory", "medium"],
    ),
    PhaseTwoCase(
        id="P2-05",
        description="Trivial greeting: minimal writes (greeting is not a memory-worthy event)",
        player_input="hi",
        player_location="Town Square",
        turn_summary="Player offered a greeting; nothing changed.",
        narration_focus="Brief acknowledgement.",
        blocked_reason="",
        narration=(
            "Thoughts: A greeting in passing; nothing requires action.\n"
            "Narrative: The square hums on around you, much as before."
        ),
        expect_finalize_writes=True,
        expected_location_after="Town Square",
        max_iterations=4,
        tags=["trivial", "easy"],
    ),
]


__all__ = ["PhaseTwoCase", "PHASE_TWO_CASES"]
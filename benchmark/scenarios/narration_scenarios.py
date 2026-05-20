from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class NarrationCase:
    id: str
    description: str
    player_input: str

    # Game state setup
    player_location: str
    npc_locations: Dict[str, str] = field(default_factory=dict)
    quest_flags: Dict[str, bool] = field(default_factory=dict)
    discovered_keys: List[str] = field(default_factory=list)
    visited_keys: List[str] = field(default_factory=list)
    conversation_history: List[str] = field(default_factory=list)
    story_status: str = ""

    # Phase 1 outputs to feed the narrator
    turn_summary: str = ""
    narration_focus: str = ""
    blocked_reason: str = ""
    action_tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    phase_one_tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    # Checks to apply to the resulting narrative
    # Supported: has_two_sections, thoughts_before_narrative, thoughts_is_first_person,
    # second_person, no_explicit_choices, minimum_length:N, concise:N,
    # no_player_agency_taken, narrative_no_the_player, narrative_no_bare_i,
    # mentions_current_location
    checks: List[str] = field(default_factory=list)
    forbidden_patterns: List[str] = field(default_factory=list)

    tags: List[str] = field(default_factory=list)


_BASE_CHECKS = [
    "has_two_sections",
    "thoughts_before_narrative",
    "second_person",
    "no_explicit_choices",
    "minimum_length:30",
    "concise:300",
    "no_player_agency_taken",
    "narrative_no_the_player",
    "narrative_no_bare_i",
]


NARRATION_CASES: List[NarrationCase] = [
    NarrationCase(
        id="NAR-01",
        description="Standard movement narration",
        player_input="I want to go to the Copper Cup",
        player_location="Copper Cup",
        visited_keys=["Town Square", "Copper Cup"],
        turn_summary="Player moved from Town Square to the Copper Cup tavern.",
        narration_focus="Describe the arrival at the Copper Cup -- the warm lamplight, the smell of ale, the regulars at the bar.",
        blocked_reason="",
        phase_one_tool_calls=[
            {"phase": "phase_one", "name": "check_can_interact",
             "arguments": {"entity_key": "Copper Cup"},
             "result": {"ok": True, "can_interact": True, "entity_type": "location"}},
        ],
        checks=_BASE_CHECKS + ["mentions_current_location"],
        forbidden_patterns=[r"\broll\b", r"\bDC\s*\d"],
        tags=["movement", "easy"],
    ),
    NarrationCase(
        id="NAR-02",
        description="Narration after a successful skill check",
        player_input="I try to sneak past the guards",
        player_location="Harbor Gate",
        npc_locations={"Gate Guard Ren": "Harbor Gate"},
        turn_summary="Player attempted to sneak past Gate Guard Ren. Stealth check succeeded with 17 vs DC 14.",
        narration_focus="Show the player slipping past unnoticed, tension and quiet.",
        blocked_reason="",
        action_tool_calls=[
            {"phase": "phase_one", "name": "skill_check",
             "arguments": {"entity_key": "Player", "skill": "stealth", "dc": 14},
             "result": {"ok": True, "success": True, "roll": 17, "total": 17, "dc": 14}},
        ],
        checks=_BASE_CHECKS,
        forbidden_patterns=[r"(?i)roll\s+(a|an|your)", r"(?i)provide\s+your\s+(bonus|modifier)"],
        tags=["mechanics", "skill_check", "medium"],
    ),
    NarrationCase(
        id="NAR-03",
        description="Narration for a blocked action",
        player_input="I head straight to the temple",
        player_location="Copper Cup",
        turn_summary="Player tried to move directly to the temple. The temple is not reachable from the Copper Cup; the player must go through the Town Square first.",
        narration_focus="Acknowledge the player's intent and gently surface the path constraint without breaking immersion.",
        blocked_reason="The temple is not directly reachable from the Copper Cup.",
        checks=_BASE_CHECKS,
        forbidden_patterns=[r"(?i)\berror\b", r"(?i)\bblocked\b"],
        tags=["blocked", "medium"],
    ),
    NarrationCase(
        id="NAR-04",
        description="Conversation narration",
        player_input="I ask Mara about the bloodstains",
        player_location="Copper Cup",
        npc_locations={"Mara": "Copper Cup"},
        turn_summary="Player asked Mara about the bloodstains on the floor. Mara was reluctant but mentioned a fight last night.",
        narration_focus="Convey Mara's reluctance through small gestures; let her words be terse and weighted.",
        blocked_reason="",
        phase_one_tool_calls=[
            {"phase": "phase_one", "name": "retrieve_memory_tool",
             "arguments": {"entity_name": "Mara"},
             "result": {"ok": True, "memories": ["Mara was upset about a brawl last night."]}},
        ],
        checks=_BASE_CHECKS + ["mentions_current_location"],
        forbidden_patterns=[r"(?i)\bnumber\s+\d+", r"(?i)what would you like"],
        tags=["social", "medium"],
    ),
    NarrationCase(
        id="NAR-05",
        description="Trivial greeting should produce short narration",
        player_input="hi",
        player_location="Town Square",
        turn_summary="Player offered a greeting; nothing of note happened in the world.",
        narration_focus="Brief acknowledgement; preserve the current scene.",
        blocked_reason="",
        checks=[
            "has_two_sections",
            "thoughts_before_narrative",
            "second_person",
            "no_explicit_choices",
            "concise:120",
            "no_player_agency_taken",
        ],
        tags=["trivial", "easy"],
    ),
]


__all__ = ["NarrationCase", "NARRATION_CASES"]
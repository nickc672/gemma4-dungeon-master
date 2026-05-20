from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class PhaseOneCase:
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

    # Expectations
    expect_finalize: bool = True
    expect_blocked: bool = False
    # Each entry: a tool name (str) or a dict with name + args, or a list (OR group).
    # Closed-world: only these names (plus finalize_turn) may be called; anything
    # else counts as an unexpected (false-positive) call.
    expected_tools_called: List[Any] = field(default_factory=list)
    # Keyword groups: each inner list is an OR group; all groups must match (AND).
    expected_turn_summary_keywords: List[List[str]] = field(default_factory=list)
    expected_narration_focus_keywords: List[List[str]] = field(default_factory=list)
    max_iterations: int = 0   # 0 means no constraint

    # Force the outcome of any skill_check (and the History roll inside
    # check_can_interact) that the model triggers during this case.
    skill_check_outcome: Optional[str] = None

    tags: List[str] = field(default_factory=list)


PHASE_ONE_CASES: List[PhaseOneCase] = [
    PhaseOneCase(
        id="P1-01",
        description="Simple movement to an adjacent location",
        player_input="I want to go to the Copper Cup",
        player_location="Town Square",
        expect_finalize=True,
        expect_blocked=False,
        expected_tools_called=["check_can_interact"],
        expected_narration_focus_keywords=[["copper", "cup", "tavern"]],
        tags=["movement", "easy"],
    ),
    PhaseOneCase(
        id="P1-02",
        description="Talk to a known NPC at the current location",
        player_input="I want to ask Mara about the bloodstains",
        player_location="Copper Cup",
        npc_locations={"Mara": "Copper Cup"},
        conversation_history=[
            "I enter the tavern.",
            "You step into the Copper Cup. Mara is behind the bar polishing a cup.",
        ],
        expect_finalize=True,
        expect_blocked=False,
        expected_tools_called=[
            ["retrieve_memory_tool", "check_can_interact"],
        ],
        expected_turn_summary_keywords=[["mara"], ["ask", "question", "speak", "talk"]],
        tags=["social", "easy"],
    ),
    PhaseOneCase(
        id="P1-03",
        description="Roll for stealth in a public space",
        player_input="I try to sneak past the guards without being seen",
        player_location="Harbor Gate",
        npc_locations={"Gate Guard Ren": "Harbor Gate"},
        expect_finalize=True,
        expected_tools_called=["skill_check"],
        expected_narration_focus_keywords=[["sneak", "stealth", "slip", "creep"]],
        tags=["mechanics", "skill_check", "medium"],
    ),
    PhaseOneCase(
        id="P1-04",
        description="Meta question about the game rules",
        player_input="Wait, can I actually pick locks in this game?",
        player_location="Town Square",
        expect_finalize=True,
        expect_blocked=False,
        expected_turn_summary_keywords=[["meta", "question", "asks", "rule"]],
        tags=["meta", "easy"],
    ),
    PhaseOneCase(
        id="P1-05",
        description="Movement to a location not reachable from here",
        player_input="I head straight to the Cleric's chambers in the temple",
        player_location="Copper Cup",
        expect_finalize=True,
        expect_blocked=True,
        expected_tools_called=["check_can_interact"],
        tags=["movement", "blocked", "medium"],
    ),
    PhaseOneCase(
        id="P1-06",
        description="Inspect an item described in scene narration",
        player_input="I take a closer look at the cracked spyglass",
        player_location="Warehouse Row",
        conversation_history=[
            "I look around.",
            "Among the crates, a cracked spyglass catches the light.",
        ],
        expect_finalize=True,
        expected_tools_called=["check_can_interact"],
        expected_narration_focus_keywords=[["spyglass"]],
        tags=["inspection", "medium"],
    ),
    PhaseOneCase(
        id="P1-07",
        description="Trivial greeting input",
        player_input="hi",
        player_location="Town Square",
        expect_finalize=True,
        expect_blocked=False,
        max_iterations=4,
        tags=["trivial", "easy"],
    ),
]


__all__ = ["PhaseOneCase", "PHASE_ONE_CASES"]
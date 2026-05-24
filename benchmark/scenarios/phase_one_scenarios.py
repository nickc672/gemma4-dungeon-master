"""
==============================
PHASE ONE BENCHMARK SCENARIOS
==============================

These cases exercise Phase 1: the read-only "plan the turn" phase.
The model reads the player's input, decides which information-gathering
tools to call, and produces a turn_summary + narration_focus for the
narrator. No world state mutates here.

The cases are arranged from easy to hard. Each one targets a real
behaviour the orchestrator depends on:

    EASY    single-action turns the model should never miss
            (move to an adjacent room, greet someone in the room,
            look at an item already in the scene)

    MEDIUM  turns that require the model to reach for the right
            read-only tool (retrieve_memory_tool on an NPC who actually
            holds a relevant memory, skill_check on the right entity
            and skill, check_can_interact that surfaces a path block)

    HARD    multi-cue turns: location memory recall for a place the
            player has visited but is no longer standing in,
            confrontations that hinge on what another off-scene
            character previously said, and code-protected interactions
            that combine a remembered clue with a skill check.

No 4th-wall meta cases. Every player_input is something the character
in the story would plausibly do or say.
"""
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

    # ------------------------------------------------------------------
    # EASY: single, clean intents the model should always handle.
    # ------------------------------------------------------------------

    PhaseOneCase(
        id="P1-01",
        description="Move to an adjacent location from Town Square",
        player_input="I push through the door of the Copper Cup",
        player_location="Town Square",
        expect_finalize=True,
        expect_blocked=False,
        expected_tools_called=["check_can_interact"],
        expected_narration_focus_keywords=[["copper", "cup", "tavern"]],
        tags=["movement", "easy"],
    ),

    PhaseOneCase(
        id="P1-02",
        description="Greet a known NPC standing in the current location",
        player_input="I catch Jorin's eye and ask how the square has been today",
        player_location="Town Square",
        npc_locations={"Street Performer Jorin": "Town Square"},
        expect_finalize=True,
        expect_blocked=False,
        expected_tools_called=[
            ["retrieve_memory_tool", "check_can_interact"],
        ],
        expected_turn_summary_keywords=[
            ["jorin"],
            ["ask", "question", "speak", "talk", "greet"],
        ],
        tags=["social", "easy"],
    ),

    PhaseOneCase(
        id="P1-03",
        description="Inspect an item the scene narration just highlighted",
        player_input="I pick up the cracked spyglass and turn it over in the light",
        player_location="Harbor Gate",
        conversation_history=[
            "I look around the gate.",
            "A cracked spyglass lies forgotten on the stone ledge by the guardpost.",
        ],
        expect_finalize=True,
        expected_tools_called=["check_can_interact", "get_entity_state"],
        expected_narration_focus_keywords=[["spyglass"]],
        tags=["item", "inspection", "easy"],
    ),

    # ------------------------------------------------------------------
    # MEDIUM: pick the right read-only tool, surface the right detail.
    # ------------------------------------------------------------------

    PhaseOneCase(
        id="P1-04",
        description=(
            "Ask an NPC about something that lives in their seeded memory. "
            "Mara's memory mentions someone testing the storeroom lock, so a "
            "good plan retrieves her memory before the narrator answers."
        ),
        player_input="I lean across the bar and ask Mara if anyone has been fiddling with the storeroom lock lately",
        player_location="Copper Cup",
        npc_locations={"Mara": "Copper Cup"},
        conversation_history=[
            "I enter the tavern.",
            "You step into the Copper Cup. Mara is behind the bar polishing a cup.",
        ],
        expect_finalize=True,
        expected_tools_called=[
            ["retrieve_memory_tool", "check_can_interact"],
        ],
        expected_turn_summary_keywords=[
            ["mara"],
            ["storeroom", "lock", "code"],
        ],
        tags=["social", "memory_recall", "medium"],
    ),

    PhaseOneCase(
        id="P1-05",
        description=(
            "Blocked movement: the player names a location that is not "
            "adjacent to where they currently stand. check_can_interact "
            "should surface the path constraint, and finalize should "
            "report blocked."
        ),
        player_input="I head straight down to the Smuggler's Entrance under the warehouses",
        player_location="Town Square",
        expect_finalize=True,
        expect_blocked=True,
        expected_tools_called=["check_can_interact", "list_world_locations"],
        tags=["movement", "blocked", "medium"],
    ),

    PhaseOneCase(
        id="P1-06",
        description="Stealth skill check at a guarded checkpoint",
        player_input="I time my steps with the lantern shadow and try to slip past Ren without him seeing me",
        player_location="Harbor Gate",
        npc_locations={"Gate Guard Ren": "Harbor Gate"},
        expect_finalize=True,
        expected_tools_called=["check_can_interact", "skill_check"],
        expected_narration_focus_keywords=[["sneak", "stealth", "slip", "creep"]],
        tags=["mechanics", "skill_check", "medium"],
    ),

    PhaseOneCase(
        id="P1-07",
        description=(
            "Ask an NPC about a portable item they are carrying. The item "
            "is held by Captain Varr, the NPC is in the same room as the "
            "player, so check_can_interact on Varr is enough; the model "
            "should NOT call retrieve_memory_tool for an in-scene target."
        ),
        player_input="I nod at Captain Varr's belt and ask if I can see the barracks keyring for a moment",
        player_location="Watch Barracks",
        npc_locations={"Captain Varr": "Watch Barracks"},
        expect_finalize=True,
        expected_tools_called=["check_can_interact", "get_entity_state", "skill_check"],
        expected_turn_summary_keywords=[
            ["varr"],
            ["key", "keyring"],
        ],
        tags=["social", "item", "medium"],
    ),

    # ------------------------------------------------------------------
    # HARD: cross-scene memory, code-gated interactions, multi-cue turns.
    # ------------------------------------------------------------------

    PhaseOneCase(
        id="P1-08",
        description=(
            "Location memory recall. The player is in Town Square but "
            "thinks back to something Pip showed them in East Alley on "
            "a previous visit. The right plan retrieves the off-scene "
            "memory (East Alley and/or Pip) rather than calling "
            "check_can_interact on entities not currently in the scene."
        ),
        player_input=(
            "I think back to that loose brick Pip pointed out in East Alley last time. "
            "Was there anything tucked behind it?"
        ),
        player_location="Town Square",
        visited_keys=["Town Square", "East Alley"],
        conversation_history=[
            "I follow Pip into East Alley.",
            "Pip crouches by a loose brick at knee height and grins before slipping away.",
            "I head back toward the square.",
        ],
        expect_finalize=True,
        expected_tools_called=["retrieve_memory_tool", "list_world_items"],
        expected_turn_summary_keywords=[
            ["east alley", "alley", "brick"],
        ],
        tags=["memory_recall", "location_memory", "hard"],
    ),

    PhaseOneCase(
        id="P1-09",
        description=(
            "Compound intent: enter a sub-room and look for the NPC who "
            "works there. The gating action is the movement into the "
            "Back Door area; Cook Brenna becomes interactable only "
            "after that, so check_can_interact on the door is the right "
            "first read."
        ),
        player_input="I slip out the back door of the tavern and look for Cook Brenna in the alley behind",
        player_location="Copper Cup",
        npc_locations={"Cook Brenna": "Back Door - Copper Cup"},
        visited_keys=["Town Square", "Copper Cup"],
        expect_finalize=True,
        expected_tools_called=["check_can_interact"],
        expected_narration_focus_keywords=[
            ["back door", "alley", "behind"],
        ],
        tags=["movement", "social", "compound", "hard"],
    ),

    PhaseOneCase(
        id="P1-10",
        description=(
            "Use a remembered clue against a locked target. The player "
            "has already found the Hidden Scrap behind the bar (it says "
            "the upstairs lock is the wedding anniversary date) and "
            "earlier learned from Brin that the anniversary is April 15. "
            "Trying the combination 0415 on the storeroom door should "
            "trigger a check_can_interact on the door, and the plan may "
            "also retrieve memory for the off-scene scrap or Mara to "
            "justify the code."
        ),
        player_input="I crouch by the storeroom door and dial the brass combination to 0415",
        player_location="Stair Landing",
        visited_keys=["Town Square", "Copper Cup", "Bar Counter", "Stair Landing"],
        conversation_history=[
            "I search the bar counter while Mara is in the back.",
            "Behind a loose crate you find a grease-stained note: 'cellar restock / upstairs lock is our wedding anniversary date'.",
            "I ask Brin about the anniversary.",
            "Brin scratches his head. 'April fifteenth, I think. Mara would know better.'",
        ],
        expect_finalize=True,
        expected_tools_called=["check_can_interact"],
        expected_turn_summary_keywords=[
            ["storeroom", "door", "lock"],
            ["0415", "code", "combination", "anniversary"],
        ],
        tags=["item", "code_clue", "memory_chain", "hard"],
    ),

    PhaseOneCase(
        id="P1-11",
        description=(
            "Confrontation with off-scene evidence. The player is in "
            "Town Square with Mitch and wants to throw Brenna's earlier "
            "testimony in his face. Brenna is not in this room, so the "
            "right plan retrieves Brenna's off-scene memory AND checks "
            "interactability with Mitch."
        ),
        player_input=(
            "I plant myself in front of Mitch and tell him Brenna saw him pacing the back door before dawn. "
            "I want to see his face when he hears it."
        ),
        player_location="Town Square",
        npc_locations={"Mitch": "Town Square"},
        visited_keys=["Town Square", "Copper Cup", "Back Door - Copper Cup"],
        conversation_history=[
            "I head out the back door of the tavern.",
            "Cook Brenna is wiping her hands on her apron, eyes tired.",
            "I ask Brenna if she has noticed anything strange.",
            "'Mitch,' she says, 'pacing right out there, before sunrise. Twice this week.'",
            "I return to the square.",
        ],
        expect_finalize=True,
        expected_tools_called=[
            "check_can_interact",
            "retrieve_memory_tool",
        ],
        expected_turn_summary_keywords=[
            ["mitch"],
            ["brenna", "back door", "pacing"],
            ["confront", "accuse", "challenge", "evidence"],
        ],
        tags=["social", "confrontation", "memory_chain", "hard"],
    ),
]


__all__ = ["PhaseOneCase", "PHASE_ONE_CASES"]
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List


# ============================================================
# test 1: Intent Parsing
# ============================================================

@dataclass
class IntentCase:
    id: str
    description: str
    player_input: str
    history_text: str
    expected_action: str
    expected_targets: List[str]
    tags: List[str] = field(default_factory=list)


INTENT_CASES: List[IntentCase] = [
    IntentCase(
        id="INT-01",
        description="Simple move Copper Cup",
        player_input="I want to go to the Copper Cup",
        history_text="",
        expected_action="move",
        expected_targets=["Copper Cup"],
        tags=["movement", "easy"],
    ),
    IntentCase(
        id="INT-02",
        description="Simple speaking to Mara",
        player_input="I want to say hi to Mara",
        history_text="",
        expected_action="talk",
        expected_targets=["Mara"],
        tags=["social", "easy"],
    ),
    IntentCase(
        id="INT-03",
        description="Use an item from inventory",
        player_input="I try using the cracked spyglass to look out toward the harbor",
        history_text="",
        expected_action="use",
        expected_targets=["Cracked Spyglass"],
        tags=["item_use", "easy"],
    ),
    IntentCase(
        id="INT-04",
        description="Attack Mitch",
        player_input="I draw my knife and lunge at Mitch",
        history_text="DM: Mitch's agitation has tipped into open hostility.",
        expected_action="attack",
        expected_targets=["Mitch"],
        tags=["attack", "easy"],
    ),
    IntentCase(
        id="INT-05",
        description="Player asks a meta question about game rules",
        player_input="Wait, can I actually pick locks in this game?",
        history_text="DM: The storeroom door has a brass four-dial combination lock.",
        expected_action="meta_question",
        expected_targets=[],
        tags=["meta", "easy"],
    ),
    IntentCase(
        id="INT-06",
        description="Move by flying, should still resolve as a move",
        player_input="I want to fly over to the Copper Cup",
        history_text="",
        expected_action="move",
        expected_targets=["Copper Cup"],
        tags=["movement", "easy"],
    ),
    IntentCase(
        id="INT-07",
        description="Inspect a named item that was mentioned earlier in the conversation",
        player_input="I examine the hidden scrap of paper",
        history_text="The player has found the Hidden Scrap clue with a cryptic message on it.",
        expected_action="inspect",
        expected_targets=["Hidden Scrap"],
        tags=["inspection", "medium"],
    ),
    IntentCase(
        id="INT-08",
        description="Take an item referenced by history",
        player_input="I pick up the coin",
        history_text="The player is standing next to the Bronze Fountain, where the Bronze Fountain Coin glints in the water.",
        expected_action="take",
        expected_targets=["Bronze Fountain Coin"],
        tags=["take_item", "medium"],
    ),
    IntentCase(
        id="INT-09",
        description="Talk to an NPC and mention moving to their location",
        player_input="I want to go to the temple and speak with Cleric Serah",
        history_text="",
        expected_action="talk",
        expected_targets=["Cleric Serah"],
        tags=["social", "medium"],
    ),
    IntentCase(
        id="INT-10",
        description="Inspect a specific detail of the environment rather than a named inventory item",
        player_input="I look at the dark stain on the doorframe of the warehouse",
        history_text="DM: the player is standing outside Warehouse Row. One doorframe bears a faded, rusty smear.",
        expected_action="inspect",
        expected_targets=["Warehouse Row"],
        tags=["inspection", "medium"],
    ),
    IntentCase(
        id="INT-11",
        description="Inspect an item referenced by an informal name",
        player_input="I take a closer look at that old rope near the docks",
        history_text="The player has noticed a frayed mooring rope coiled near the pier, one end stained darker than the rest.",
        expected_action="inspect",
        expected_targets=["Frayed Mooring Rope"],
        tags=["inspection", "medium"],
    ),
    IntentCase(
        id="INT-12",
        description="Confusing input that could be parsed as either a move or an inspect action",
        player_input="I head over to the old well to check out the stains on the stones",
        history_text="",
        expected_action="inspect",
        expected_targets=["Old Well"],
        tags=["inspect", "medium"],
    ),
    IntentCase(
        id="INT-13",
        description="Persuade a NPC to bypass checks",
        player_input="I try to convince Gate Guard Ren to let me through without checking my papers",
        history_text="DM: Ren eyes you carefully at the harbor gate.",
        expected_action="talk",
        expected_targets=["Gate Guard Ren"],
        tags=["social", "medium"],
    ),
    IntentCase(
        id="INT-14",
        description="Talk to an NPC referenced only by pronoun, name mentioned in history",
        player_input="I want to ask her about the bloodstains",
        history_text="Mara watches you from behind the bar counter, polishing a copper cup.",
        expected_action="talk",
        expected_targets=["Mara"],
        tags=["social", "medium", "pronoun"],
    ),
    IntentCase(
        id="INT-15",
        description="Take an item referenced only by pronoun, name mentioned in history",
        player_input="I pick it up",
        history_text=(
            "DM: The guard's lost signet ring lies on the cobblestones at your feet, "
            "freshly dropped and glinting in the lamplight."
        ),
        expected_action="take",
        expected_targets=["Guard's Lost Signet"],
        tags=["item_use", "medium", "pronoun"],
    ),
    IntentCase(
        id="INT-16",
        description="Move to a location using side route rather than the main entrance",
        player_input="I slip in through the back door of the Copper Cup",
        history_text="DM: You are in East Alley. The back door to the Copper Cup is visible ahead.",
        expected_action="move",
        expected_targets=["Back Door - Copper Cup"],
        tags=["movement", "medium"],
    ),
    IntentCase(
        id="INT-17",
        description="Inspect a clue by using question about what a note actually says",
        player_input="I read the note more carefully, what does it actually say about the lock?",
        history_text=(
            "DM: You found a hidden scrap note behind a loose crate. "
            "It mentions a cellar restock and that the upstairs lock is a wedding anniversary date."
        ),
        expected_action="inspect",
        expected_targets=["Hidden Scrap"],
        tags=["inspection", "hard"],
    ),
    IntentCase(
        id="INT-18",
        description="Talk to two named NPCs in a single input",
        player_input="I want to ask Jorin and Old Tellan what they know about the well",
        history_text="",
        expected_action="talk",
        expected_targets=["Street Performer Jorin", "Old Tellan"],
        tags=["social", "hard", "multi-target"],
    ),
    IntentCase(
        id="INT-19",
        description="Show a named item from inventory to a specific NPC",
        player_input="I show the smugglers' ledger to Dockmaster Hara",
        history_text="DM: You found the Smugglers' Ledger hidden in the warehouse. Hara is nearby on the docks.",
        expected_action="use",
        expected_targets=["Smugglers' Ledger", "Dockmaster Hara"],
        tags=["item_use", "hard", "multi-target"],
    ),
    IntentCase(
        id="INT-20",
        description="move to find NPC to show them a specific item",
        player_input="I find Smuggler Lia and show her the frayed mooring rope to see if she recognizes it",
        history_text="DM: You are currently at the docks. Lia is rumored to lurk near Smuggler's Entrance.",
        expected_action="use",
        expected_targets=["Frayed Mooring Rope", "Smuggler Lia"],
        tags=["item_use", "hard", "multi-target"],
    ),
]










# ============================================================
# test 2: Intent Phase
# ============================================================

@dataclass
class IntentPhaseCase:
    id: str
    description: str

    player_input: str
    player_location: str
    intent: Dict[str, Any]
    beat_index: int = 0
    discovered_keys: List[str] = field(default_factory=list)
    npc_locations: Dict[str, str] = field(default_factory=dict)
    quest_flags: Dict[str, bool] = field(default_factory=dict)
    conversation_history: List[str] = field(default_factory=list)
    story_status: str = ""
    session_summary: str = ""

    expect_todo_created: bool = True
    expect_summary: bool = True
    expect_decision_summary: bool = True

    min_todo_items: int = 1
    max_todo_items: int = 4

    # Each entry is a dict with "name" and optional "args".
    # e.g. {"name": "get_world_location", "args": {"location_key": "Copper Cup"}}
    expected_inspection_tools: List[Any] = field(default_factory=list)

    # Keyword groups - the todo content scoring.
    # Each inner list is an OR group; all groups must match.
    # e.g. [["player"], ["copper", "cup"], ["move", "update"]]
    expected_todo_keywords: List[List[str]] = field(default_factory=list)

    expected_iterations: int = 0 # 0 = don't check
    expected_tool_call_rounds: List[int] = field(default_factory=list)

    tags: List[str] = field(default_factory=list)


INTENT_PHASE_CASES: List[IntentPhaseCase] = [
    IntentPhaseCase(
        id="IPHASE-01",
        description="Simple move to an adjacent location",
        player_input="I walk to the Copper Cup.",
        player_location="Town Square",
        intent={
            "action": "move", "action_category": "move",
            "targets": ["Copper Cup"],
        },
        beat_index=0,
        discovered_keys=["Town Square"],
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=1,
        max_todo_items=4,
        expected_inspection_tools=[
            {"name": "get_world_location", "args": {"location_key": "Copper Cup"}},
        ],
        expected_todo_keywords=[
            ["player"],
            ["copper cup"],
            ["move", "update"],
        ],
        expected_iterations=0,
        expected_tool_call_rounds=[0],
        tags=["movement", "easy"],
    ),

    IntentPhaseCase(
        id="IPHASE-02",
        description="Talk to Mara who is at Copper Cup but at the Bar location",
        player_input="I talk to Mara about what she knows.",
        player_location="Copper Cup",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Mara"],
        },
        beat_index=1,
        discovered_keys=["Town Square", "Copper Cup"],
        conversation_history=[
            "Player: I walk into the Copper Cup.",
            "DM: The low-beamed tavern is warm and smells of stew.",
        ],
        session_summary="Intro: You arrived at dusk.\nRecap: You entered the Copper Cup.",
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=1,
        max_todo_items=4,
        expected_inspection_tools=[
            {"name": "check_can_interact", "args": {"entity_key": "Mara"}},
        ],
        expected_todo_keywords=[
            ["mara"],
            ["player"],
            ["talk", "speak", "ask", "converse", "interact"],
            ["move", "update"],
            ["bar counter"]
        ],
        tags=["social", "movement", "medium"],
    ),

    IntentPhaseCase(
        id="IPHASE-03",
        description="Talk to Brin, NPC also present at the Copper Cup",
        player_input="I go over and introduce myself to Brin.",
        player_location="Copper Cup",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Brin"],
        },
        beat_index=1,
        discovered_keys=["Town Square", "Copper Cup"],
        conversation_history=[
            "Player: I walk into the Copper Cup.",
            "DM: The tavern hums. Behind the counter Mara polishes cups while Brin nurses a drink at the far end of the bar.",
        ],
        session_summary="Intro: You arrived at dusk.\nRecap: You entered the Copper Cup.",
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=1,
        max_todo_items=4,
        expected_inspection_tools=[
            {"name": "check_can_interact", "args": {"entity_key": "Brin"}},
            {"name": "get_entity_state", "args": {"entity_key": "Brin", "include_memory_preview": True}},
        ],
        expected_todo_keywords=[
            ["brin"],
            ["talk", "speak", "ask", "introduce", "introduction", "approach"],
        ],
        tags=["social", "easy"],
    ),

    IntentPhaseCase(
        id="IPHASE-04",
        description="Inspect the current location for details",
        player_input="I look around the market stalls.",
        player_location="Market Stalls",
        intent={
            "action": "inspect", "action_category": "inspect",
            "targets": ["Market Stalls"],
        },
        beat_index=0,
        discovered_keys=["Town Square", "Market Stalls"],
        conversation_history=[
            "Player: I walk to the Market Stalls.",
            "DM: Canvas-topped stalls crowd the edge of the square.",
        ],
        session_summary="Intro: You arrived at dusk in the harbor town.",
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=1,
        max_todo_items=4,
        expected_inspection_tools=[
            [
                {"name": "get_world_location", "args": {"location_key": "Market Stalls"}},
                "list_scene_entities", #either or both of these works
            ]
        ],
        expected_todo_keywords=[
            ["market", "stall"],
            ["inspect", "examine", "search", "look"],
        ],
        tags=["inspection", "easy"],
    ),

    IntentPhaseCase(
        id="IPHASE-05",
        description="Inspect the Bar Counter for hidden clues",
        player_input="I lean over the counter and look for anything hidden behind the bottles.",
        player_location="Bar Counter",
        intent={
            "action": "inspect", "action_category": "inspect",
            "targets": ["Bar Counter"],
        },
        beat_index=1,
        discovered_keys=["Town Square", "Copper Cup", "Bar Counter"],
        conversation_history=[
            "Player: I step up to the bar.",
            "DM: Mara glances up. The shelves behind her are cluttered with bottles, a till, and stacked crates below.",
        ],
        session_summary="Intro: You arrived at dusk.\nRecap: You are at the bar counter in the Copper Cup.",
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=1,
        max_todo_items=4,
        expected_inspection_tools=[],
        expected_todo_keywords=[
            ["skill_check"],
            ["entity_key:"],
            ["player"],
            ["skill"],
            ["perception"],
        ],
        expected_iterations=1,
        tags=["inspection", "easy"],
    ),

    IntentPhaseCase(
        id="IPHASE-06",
        description="Take an item that is at the current location",
        player_input="I pick up the carved driftwood charm from the offering bowl.",
        player_location="Old Shrine",
        intent={
            "action": "take", "action_category": "take",
            "targets": ["Carved Driftwood Charm"],
        },
        beat_index=2,
        discovered_keys=["Town Square", "East Alley", "Old Shrine"],
        conversation_history=[
            "Player: I slip into the old shrine.",
            "DM: The crumbling shrine smells of salt. A carved driftwood charm rests in the offering bowl.",
        ],
        session_summary="Intro: You arrived at dusk.\nRecap: You found the Old Shrine in the alley.",
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=1,
        max_todo_items=4,
        expected_inspection_tools=[
            {"name": "check_can_interact", "args": {"entity_key": "Carved Driftwood Charm"}},
        ],
        expected_todo_keywords=[
            ["charm", "driftwood"],
            ["add", "take", "pick", "collect", "retrieve"],
        ],
        tags=["take_item", "easy"],
    ),

    IntentPhaseCase(
        id="IPHASE-07",
        description="Blocked move, destination not adjacent",
        player_input="I head down to the Docks.",
        player_location="Town Square",
        intent={
            "action": "move", "action_category": "move",
            "targets": ["Docks"],
        },
        beat_index=0,
        discovered_keys=["Town Square"],
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=1,
        max_todo_items=4,
        expected_inspection_tools=[
            {"name": "get_world_location", "args": {"location_key": "Docks"}},
        ],
        expected_todo_keywords=[
            ["dock"],
            ["don't move", "check", "verify", "don't travel", "blocked"],
        ],
        tags=["movement", "medium", "blocked"],
    ),

    IntentPhaseCase(
        id="IPHASE-08",
        description="Reach NPC at a different location before talking",
        player_input="I go back to the town square and find Mitch and ask him about the bloodstains.",
        player_location="Copper Cup",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Mitch"],
        },
        beat_index=0,
        discovered_keys=["Town Square", "Copper Cup"],
        session_summary="Intro: You arrived at dusk in the harbor town and noticed several people and places around.  Recap: You decided to visit the Copper Cup.",
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=1,
        max_todo_items=4,
        expected_inspection_tools=[
            {"name": "get_world_location", "args": {"location_key": "Town Square"}},
            {"name": "check_can_interact", "args": {"entity_key": "Mitch"}},
        ],
        expected_todo_keywords=[
            ["mitch"],
            ["skill_check"],
            ["persuasion"],
        ],
        tags=["multi-tool", "social", "movement", "medium"],
    ),

    IntentPhaseCase(
        id="IPHASE-09",
        description="Inspection of a hidden area",
        player_input="I carefully search the alley for anything hidden.",
        player_location="East Alley",
        intent={
            "action": "inspect", "action_category": "inspect",
            "targets": ["East Alley"],
        },
        beat_index=2,
        discovered_keys=["Town Square", "East Alley"],
        conversation_history=[
            "Player: I slip into the East Alley.",
            "DM: The narrow alley is shadowed and very quiet.",
        ],
        story_status="The investigation is underway.",
        session_summary="Intro: You arrived at dusk.\nRecap: You entered the East Alley.",
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=1,
        max_todo_items=4,
        expected_inspection_tools=[],
        expected_todo_keywords=[
            ["skill_check"],
            ["perception"],
        ],
        tags=["inspection", "medium"],
    ),

    IntentPhaseCase(
        id="IPHASE-10",
        description="Show a named item from inventory to an NPC at the current location",
        player_input="I show the smugglers' ledger to Dockmaster Hara.",
        player_location="Docks",
        intent={
            "action": "use", "action_category": "use",
            "targets": ["Smugglers' Ledger", "Dockmaster Hara"],
        },
        beat_index=3,
        discovered_keys=["Town Square", "Harbor Gate", "Docks"],
        conversation_history=[
            "Player: I walk down to the docks.",
            "DM: Dockmaster Hara stands at the end of the pier, reviewing a manifest.",
        ],
        story_status="The player has found a smugglers' ledger in the warehouse.",
        session_summary="Intro: You arrived at dusk.\nRecap: You found the ledger and headed to the docks.",
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=1,
        max_todo_items=4,
        expected_inspection_tools=[
            {"name": "check_can_interact", "args": {"entity_key": "Dockmaster Hara"}},
        ],
        expected_todo_keywords=[
            ["ledger"],
            ["hara"],
            ["show", "present", "use", "display"],
        ],
        tags=["item_use", "medium"],
    ),

    IntentPhaseCase(
        id="IPHASE-11",
        description="Talk to Gate Guard Ren and ask about Docks access",
        player_input="I approach Ren at the gate and ask him what it takes to get through to the docks.",
        player_location="Harbor Gate",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Gate Guard Ren"],
        },
        beat_index=1,
        discovered_keys=["Town Square", "Harbor Gate"],
        conversation_history=[
            "Player: I walk up to the Harbor Gate.",
            "DM: Ren leans on his spear, eyeing the flow of carts. He nods as you approach.",
        ],
        session_summary="Intro: You arrived at dusk.\nRecap: You reached the Harbor Gate.",
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=1,
        max_todo_items=4,
        expected_inspection_tools=[
            {"name": "check_can_interact", "args": {"entity_key": "Gate Guard Ren"}},
            {"name": "get_world_location", "args": {"location_key": "Harbor Gate"}},
        ],
        expected_todo_keywords=[
            ["ren", "guard"],
            ["talk", "speak", "ask", "question"],
        ],
        tags=["social", "medium", "multi-tool"],
    ),

    IntentPhaseCase(
        id="IPHASE-12",
        description="Talk to Spice Seller Nima at the Market Stalls",
        player_input="I head to Nima's stall and ask her if she's sold anything unusual lately.",
        player_location="Market Stalls",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Spice Seller Nima"],
        },
        beat_index=2,
        discovered_keys=["Town Square", "Market Stalls"],
        conversation_history=[
            "Player: I wander through the market.",
            "DM: Nima's stall is still open, jars of spice ranked in careful rows. She watches you with sharp eyes.",
        ],
        story_status="Strange purchase patterns have been noted near the market.",
        session_summary="Intro: You arrived at dusk.\nRecap: You are investigating the Market Stalls.",
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=1,
        max_todo_items=4,
        expected_inspection_tools=[
            {"name": "check_can_interact", "args": {"entity_key": "Spice Seller Nima"}},
            {"name": "list_world_items", "args": {"holder_key": "Nima"}},
        ],
        expected_todo_keywords=[
            ["nima"],
            ["talk", "speak", "ask", "question"],
        ],
        tags=["social", "medium"],
    ),

    IntentPhaseCase(
        id="IPHASE-13",
        description="Move from Harbor Gate to Watch Barracks to speak with Captain Varr",
        player_input="I want to find Captain Varr at the barracks and ask him about the patrol reports.",
        player_location="Harbor Gate",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Captain Varr"],
        },
        beat_index=2,
        discovered_keys=["Town Square", "Harbor Gate"],
        conversation_history=[
            "Player: I ask a guard where Varr is stationed.",
            "DM: The guard jerks his thumb toward the Watch Barracks just off the gate.",
        ],
        story_status="Patrol reports have been edited and Varr is known to be suspicious of the wizard.",
        session_summary="Intro: You arrived at dusk.\nRecap: You are at the Harbor Gate investigating the watch.",
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=2,
        max_todo_items=5,
        expected_inspection_tools=[
            {"name": "get_world_location", "args": {"location_key": "Watch Barracks"}},
            {"name": "check_can_interact", "args": {"entity_key": "Captain Varr"}},
            {"name": "get_entity_state", "args": {"entity_key": "Captain Varr", "include_memory_preview": True}}, #get_world_entity maybe too?
        ],
        expected_todo_keywords=[
            ["varr", "captain"],
            ["talk", "speak", "ask", "find"],
        ],
        tags=["social", "medium", "multi-tool"],
    ),

    IntentPhaseCase(
        id="IPHASE-14",
        description="Inspect Warehouse Row for the hidden Smugglers' Ledger",
        player_input="I search the warehouses for anything that looks like records or hidden cargo manifests.",
        player_location="Warehouse Row",
        intent={
            "action": "inspect", "action_category": "inspect",
            "targets": ["Warehouse Row"],
        },
        beat_index=2,
        discovered_keys=["Town Square", "Harbor Gate", "Docks", "Warehouse Row"],
        conversation_history=[
            "Player: I walk along the waterfront toward the warehouses.",
            "DM: The heavy doors of Warehouse Row are mostly shut. One doorframe shows that rusty smear.",
        ],
        story_status="Smuggling activity is suspected. A ledger is rumored to be hidden somewhere in the warehouses.",
        session_summary="Intro: You arrived at dusk.\nRecap: You are investigating the waterfront area.",
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=1,
        max_todo_items=4,
        expected_inspection_tools=[
            {"name": "get_world_location", "args": {"location_key": "Warehouse Row"}},
            {"name": "check_can_interact", "args": {"entity_key": "Smugglers' Ledger"}},
        ],
        expected_todo_keywords=[
            ["skill_check"],
            ["investigation"],
        ],
        tags=["inspection", "medium", "multi-tool"],
    ),

    IntentPhaseCase(
        id="IPHASE-15",
        description="Attack on an NPC",
        player_input="I draw my knife and lunge at Mitch.",
        player_location="Copper Cup",
        intent={
            "action": "attack", "action_category": "attack",
            "targets": ["Mitch"],
        },
        beat_index=2,
        discovered_keys=["Town Square", "Copper Cup"],
        conversation_history=[
            "Player: I confront Mitch about the bloodstains.",
            "DM: Mitch's face darkens. He shoves a stool aside and reaches for something at his belt.",
        ],
        story_status="Mitch has turned hostile.",
        session_summary="Intro: You arrived at dusk.\nRecap: You confronted Mitch at the Copper Cup.",
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=1,
        max_todo_items=4,
        expected_inspection_tools=[
            {"name": "check_can_interact", "args": {"entity_key": "Mitch"}},
            {"name": "get_entity_state", "args": {"entity_key": "Player"}}, #for inventory check for weapon
            {"name": "get_entity_state", "args": {"entity_key": "Mitch"}}, #for health 

        ],
        expected_todo_keywords=[
            ["mitch"],
            ["attack", "combat", "fight", "lunge", "strike"],
            ["skill_check"],
        ],
        tags=["attack", "hard"],
    ),

    IntentPhaseCase(
        id="IPHASE-16",
        description="Talk to two NPCs in a single action",
        player_input="I want to ask both Jorin and Old Tellan what they know about the well.",
        player_location="Town Square",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Street Performer Jorin", "Old Tellan"],
        },
        beat_index=1,
        discovered_keys=["Town Square"],
        conversation_history=[
            "Player: I look around the square.",
            "DM: Jorin juggles near the fountain. Old Tellan sits on the well's rim spinning a story.",
        ],
        story_status="Strange lights have been seen near the old well.",
        session_summary="Intro: You arrived at dusk.\nRecap: You explored Town Square.",
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=2,
        max_todo_items=5,
        expected_inspection_tools=[
            {"name": "check_can_interact", "args": {"entity_key": "Jorin"}},
            {"name": "check_can_interact", "args": {"entity_key": "Old Tellan"}},
        ],
        expected_todo_keywords=[
            ["jorin", "tellan"],
            ["move", "walk", "go"],
            ["talk", "speak", "ask"],
            ["old well"]
        ],
        tags=["social", "hard", "multi-target", "multi-tool"],
    ),

    IntentPhaseCase(
        id="IPHASE-17",
        description="Move to find Smuggler Lia then show her the Frayed Mooring Rope",
        player_input="I find Smuggler Lia and show her the frayed mooring rope to see if she recognizes it.",
        player_location="Docks",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Smuggler Lia", "Frayed Mooring Rope"],
        },
        beat_index=3,
        discovered_keys=["Town Square", "Harbor Gate", "Docks"],
        conversation_history=[
            "Player: I search the docks area.",
            "DM: You spot fraying rope near the pier. Lia is rumored near the Smuggler's Entrance.",
        ],
        story_status="The bloodstain investigation points toward smuggling activity.",
        session_summary="Intro: You arrived at dusk.\nRecap: You found the frayed rope and are searching for Lia.",
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=2,
        max_todo_items=5,
        expected_inspection_tools=[
            {"name": "get_world_location", "args": {"location_key": "Smuggler's Entrance"}},
            {"name": "check_can_interact", "args": {"entity_key": "Smuggler Lia"}},
        ],
        expected_todo_keywords=[
            ["lia"],
            ["rope", "mooring"],
            ["show", "find", "present", "locate"],
        ],
        tags=["social", "hard", "multi-target", "multi-tool"],
    ),

    IntentPhaseCase(
        id="IPHASE-18",
        description="Investigate South Bridge and question Bridge Watcher Sol",
        player_input="I want to look around the South Bridge and talk to whoever is on watch there.",
        player_location="South Bridge",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Bridge Watcher Sol"],
        },
        beat_index=2,
        discovered_keys=["Town Square", "South Bridge"],
        conversation_history=[
            "Player: I cross toward the South Bridge.",
            "DM: Lanterns line the parapet. A figure leans on the railing - Bridge Watcher Sol.",
        ],
        story_status="Locals report waking on the bridge with aching feet and no memory of how they arrived.",
        session_summary="Intro: You arrived at dusk.\nRecap: You are investigating the South Bridge.",
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=2,
        max_todo_items=5,
        expected_inspection_tools=[
            {"name": "get_world_location", "args": {"location_key": "South Bridge"}},
            {"name": "check_can_interact", "args": {"entity_key": "Sol"}},
        ],
        expected_todo_keywords=[
            ["sol", "bridge"],
            ["talk", "speak", "ask", "question", "investigate"],
        ],
        tags=["social", "inspection", "hard", "multi-tool"],
    ),

    IntentPhaseCase(
        id="IPHASE-19",
        description="Talk to Fisher Mira and Fisher Rian at Fishermen's Shacks",
        player_input="I want to head over to the fishermen's shacks and speak with Mira and Rian about what they've seen at night.",
        player_location="Docks",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Fisher Mira", "Fisher Rian"],
        },
        beat_index=3,
        discovered_keys=["Town Square", "Harbor Gate", "Docks"],
        conversation_history=[
            "Player: I ask around the docks about witnesses.",
            "DM: A sailor points toward the shacks upriver - Fisher Mira and old Rian are usually there at this hour.",
        ],
        story_status="Witnesses near the river have reported waking with wet boots and no memory of leaving bed.",
        session_summary="Intro: You arrived at dusk.\nRecap: You are investigating the harbor and river area.",
        npc_locations={
            "Fisher Mira": "Fishermen's Shacks",
            "Fisher Rian": "Fishermen's Shacks",
        },
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=2,
        max_todo_items=6,
        expected_inspection_tools=[
            {"name": "get_world_location", "args": {"location_key": "Fishermen's Shacks"}},
            {"name": "check_can_interact", "args": {"entity_key": "Fisher Mira"}}, #maybe should be get_world_entity if player location wont be updated?
            {"name": "check_can_interact", "args": {"entity_key": "Fisher Rian"}},
        ],
        expected_todo_keywords=[
            ["mira", "rian", "fisher"],
            ["talk", "speak", "ask"],
        ],
        tags=["social", "hard", "multi-target", "multi-tool"],
    ),

    IntentPhaseCase(
        id="IPHASE-20",
        description="Break into the storeroom using Pip's lockpick set",
        player_input="I want to get into the storeroom, I'll use the lockpick set to crack the combination lock on the door.",
        player_location="Copper Cup",
        intent={
            "action": "use", "action_category": "use",
            "targets": ["Bent Lockpick Set", "Storeroom Door"],
        },
        beat_index=2,
        discovered_keys=["Town Square", "Copper Cup", "Stair Landing"],
        conversation_history=[
            "Player: I ask around about the storeroom upstairs.",
            "DM: The Stair Landing leads up. A stout oak door with a brass four-dial lock blocks the way.",
            "Player: I want to get into the storeroom using a lockpick set.",
        ],
        story_status="The storeroom is locked with a four-dial combination lock. Pip in the East Alley is known to carry lockpicks.",
        session_summary="Intro: You arrived at dusk.\nRecap: You are trying to access the locked storeroom in the Copper Cup.",
        npc_locations={
            "Street Urchin Pip": "East Alley",
        },
        expect_todo_created=True,
        expect_summary=True,
        expect_decision_summary=True,
        min_todo_items=2,
        max_todo_items=6,
        expected_inspection_tools=[
            {"name": "get_world_location", "args": {"location_key": "Stair Landing"}}, #its doing Stair Landing, not storeroom door.
            {"name": "check_can_interact", "args": {"entity_key": "Stair Landing"}},
            {"name": "check_can_interact", "args": {"entity_key": "Bent Lockpick Set"}},
        ],

        #get_entity_state{"entity_key": "Storeroom Door", "include_memory_preview": false, "memory_preview": 0}
        #{"success": false, "reason": "Entity 'Storeroom Door' not found."}
        expected_todo_keywords=[
            ["storeroom", "lock", "door"],
            ["lockpick", "pick", "open", "access", "unlock"],
        ],
        tags=["item_use", "hard", "multi-tool", "blocked"],
    ),
]










# ============================================================
# test 3: Mechanics Phase
# ============================================================

@dataclass
class MechanicsPhaseCase:
    id: str
    description: str

    player_input: str
    player_location: str
    intent: Dict[str, Any]
    beat_index: int = 0
    discovered_keys: List[str] = field(default_factory=list)
    npc_locations: Dict[str, str] = field(default_factory=dict)
    quest_flags: Dict[str, bool] = field(default_factory=dict)
    conversation_history: List[str] = field(default_factory=list)
    story_status: str = ""
    session_summary: str = ""

    todo_items: List[Dict[str, Any]] = field(default_factory=list)
    todo_summary: str = ""
    intent_summary: str = ""

    expected_tools_called: List[Any] = field(default_factory=list)
    should_not_call: List[str] = field(default_factory=list)
    expected_location_after: str = ""
    expect_all_resolved: bool = True
    expect_blocked_items: bool = False
    expect_summary: bool = True
    tags: List[str] = field(default_factory=list)


MECHANICS_PHASE_CASES: List[MechanicsPhaseCase] = [
    MechanicsPhaseCase(
        id="MPHASE-01",
        description="Simple successful move to an adjacent location",
        player_input="I walk to the Copper Cup.",
        player_location="Town Square",
        intent={
            "action": "move", "action_category": "move",
            "targets": ["Copper Cup"],
        },
        beat_index=0,
        discovered_keys=["Town Square"],
        todo_items=[
            {"task": "Move player to the Copper Cup.", "requires_tool": True},
        ],
        todo_summary="Move the player to the Copper Cup.",
        intent_summary="Move the player to the Copper Cup.",
        expected_tools_called=[
            {"name": "move_to_location", "args": {"location_key": "Copper Cup"}},
        ],
        expected_location_after="Copper Cup",
        expect_all_resolved=True,
        expect_blocked_items=False,
        expect_summary=True,
        tags=["movement", "easy"],
    ),
    MechanicsPhaseCase(
        id="MPHASE-02",
        description="Successful move between two adjacent harbor locations",
        player_input="I walk down to the Docks.",
        player_location="Harbor Gate",
        intent={
            "action": "move", "action_category": "move",
            "targets": ["Docks"],
        },
        beat_index=2,
        discovered_keys=["Town Square", "Harbor Gate"],
        session_summary="Intro: You arrived at dusk.\nRecap: You reached the Harbor Gate.",
        todo_items=[
            {"task": "Move player to the Docks from Harbor Gate.", "requires_tool": True},
        ],
        todo_summary="Move the player to the Docks.",
        intent_summary="Move the player to the Docks.",
        expected_tools_called=[
            {"name": "move_to_location", "args": {"location_key": "Docks"}},
        ],
        expected_location_after="Docks",
        expect_all_resolved=True,
        expect_blocked_items=False,
        expect_summary=True,
        tags=["movement", "easy"],
    ),
    MechanicsPhaseCase(
        id="MPHASE-03",
        description="Move from Town Square to Temple of the Tide, which is directly adjacent",
        player_input="I head to the Temple of the Tide.",
        player_location="Town Square",
        intent={
            "action": "move", "action_category": "move",
            "targets": ["Temple of the Tide"],
        },
        beat_index=1,
        discovered_keys=["Town Square"],
        session_summary="Intro: You arrived at dusk in the harbor town.",
        todo_items=[
            {"task": "Move player to the Temple of the Tide.", "requires_tool": True},
        ],
        todo_summary="Move the player to the Temple of the Tide.",
        intent_summary="Move the player to the Temple of the Tide.",
        expected_tools_called=[
            {"name": "move_to_location", "args": {"location_key": "Temple of the Tide"}},
        ],
        expected_location_after="Temple of the Tide",
        expect_all_resolved=True,
        expect_blocked_items=False,
        expect_summary=True,
        tags=["movement", "easy"],
    ),
    MechanicsPhaseCase(
        id="MPHASE-04",
        description="Talk to NPC at current location, doesnt need any tools",
        player_input="I talk to Mara about what she knows.",
        player_location="Copper Cup",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Mara"],
        },
        beat_index=1,
        discovered_keys=["Town Square", "Copper Cup"],
        conversation_history=[
            "Player: I walk into the Copper Cup.",
            "DM: The low-beamed tavern is warm. Mara watches you.",
        ],
        session_summary="Intro: You arrived at dusk.\nRecap: You entered the Copper Cup.",
        todo_items=[
            {"task": "Resolve conversation with Mara.", "requires_tool": False},
        ],
        todo_summary="Resolve conversation with Mara.",
        intent_summary="Resolve conversation with Mara.",
        expected_tools_called=[],
        should_not_call=["move_to_location", "move_npc", "check_can_interact"],
        expected_location_after="Copper Cup",
        expect_all_resolved=True,
        expect_blocked_items=False,
        expect_summary=True,
        tags=["social", "easy"],
    ),
    MechanicsPhaseCase(
        id="MPHASE-05",
        description="Talk to Brin at Copper Cup, no tools needed",
        player_input="I introduce myself to Brin.",
        player_location="Copper Cup",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Brin"],
        },
        beat_index=1,
        discovered_keys=["Town Square", "Copper Cup"],
        conversation_history=[
            "Player: I step inside the Copper Cup.",
            "DM: Brin nurses a drink at the far end of the bar, weathered and quiet.",
        ],
        session_summary="Intro: You arrived at dusk.\nRecap: You entered the Copper Cup.",
        todo_items=[
            {"task": "Resolve introduction with Brin.", "requires_tool": False},
        ],
        todo_summary="Resolve introduction with Brin.",
        intent_summary="Resolve introduction with Brin.",
        expected_tools_called=[],
        should_not_call=["move_to_location", "move_npc", "skill_check", "check_can_interact", "get_world_entity"],
        expected_location_after="Copper Cup",
        expect_all_resolved=True,
        expect_blocked_items=False,
        expect_summary=True,
        tags=["social", "easy"],
    ),
    MechanicsPhaseCase(
        id="MPHASE-06",
        description="Talk to Deckhand Finn at the Docks, no tools needed",
        player_input="I ask Finn what he saw at the docks last night.",
        player_location="Docks",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Deckhand Finn"],
        },
        beat_index=2,
        discovered_keys=["Town Square", "Harbor Gate", "Docks"],
        conversation_history=[
            "Player: I walk down to the docks.",
            "DM: Deckhand Finn coils rope near the pier, watching the water.",
        ],
        story_status="Bloodstains have appeared near the pump well.",
        session_summary="Intro: You arrived at dusk.\nRecap: You made your way to the Docks.",
        todo_items=[
            {"task": "Resolve conversation with Deckhand Finn about last night.", "requires_tool": False},
        ],
        todo_summary="Resolve conversation with Deckhand Finn.",
        intent_summary="Resolve conversation with Deckhand Finn about what he saw.",
        expected_tools_called=[],
        should_not_call=["move_to_location", "move_npc"],
        expected_location_after="Docks",
        expect_all_resolved=True,
        expect_blocked_items=False,
        expect_summary=True,
        tags=["social", "easy"],
    ),

    MechanicsPhaseCase(
        id="MPHASE-07",
        description="Blocked move because the destination is not adjacent",
        player_input="I head down to the Docks.",
        player_location="Town Square",
        intent={
            "action": "move", "action_category": "move",
            "targets": ["Docks"],
        },
        beat_index=0,
        discovered_keys=["Town Square"],
        todo_items=[
            {"task": "Attempt to move player to the Docks.", "requires_tool": True},
        ],
        todo_summary="Attempt to move the player to the Docks.",
        intent_summary="Attempt to move the player to the Docks.",
        expected_tools_called=[
            {"name": "move_to_location", "args": {"location_key": "Docks"}},
        ],
        expected_location_after="Town Square",
        expect_all_resolved=True,
        expect_blocked_items=True,
        expect_summary=True,
        tags=["movement", "medium", "blocked"],
    ),
    MechanicsPhaseCase(
        id="MPHASE-08",
        description="Blocked move from Harbor Gate to Smuggler's Entrance",
        player_input="I slip down to the Smuggler's Entrance.",
        player_location="Harbor Gate",
        intent={
            "action": "move", "action_category": "move",
            "targets": ["Smuggler's Entrance"],
        },
        beat_index=2,
        discovered_keys=["Town Square", "Harbor Gate", "Warehouse Row"],
        conversation_history=[
            "Player: I ask around about a hidden entrance near the warehouses.",
            "DM: A dockhand glances around and mutters something about a grate near the old well.",
        ],
        story_status="The investigation points toward smuggling tunnels beneath the warehouses.",
        session_summary="Intro: You arrived at dusk.\nRecap: You learned of the Smuggler's Entrance.",
        todo_items=[
            {"task": "Attempt to move player to the Smuggler's Entrance.", "requires_tool": True},
        ],
        todo_summary="Attempt to move the player to the Smuggler's Entrance.",
        intent_summary="Attempt to move the player to the Smuggler's Entrance from Harbor Gate.",
        expected_tools_called=[
            {"name": "move_to_location", "args": {"location_key": "Smuggler's Entrance"}},
        ],
        expected_location_after="Harbor Gate",
        expect_all_resolved=True,
        expect_blocked_items=True,
        expect_summary=True,
        tags=["movement", "medium", "blocked"],
    ),
    MechanicsPhaseCase(
        id="MPHASE-09",
        description="Perception check to search for a hidden clue in the alley",
        player_input="I search the alley for hidden clues.",
        player_location="East Alley",
        intent={
            "action": "inspect", "action_category": "inspect",
            "targets": ["East Alley"],
        },
        beat_index=2,
        discovered_keys=["Town Square", "East Alley"],
        conversation_history=[
            "Player: I slip into the East Alley.",
            "DM: The narrow alley is shadowed and quiet.",
        ],
        story_status="The investigation is underway.",
        session_summary="Intro: You arrived at dusk.\nRecap: You entered the East Alley.",
        todo_items=[
            {"task": "Perform a perception check for hidden clues in East Alley.", "requires_tool": True},
        ],
        todo_summary="Search East Alley with a perception check.",
        intent_summary="Search East Alley with a perception check.",
        expected_tools_called=[
            {"name": "skill_check", "args": {"entity_key": "Player", "skill": "perception"}},
        ],
        should_not_call=["move_to_location", "move_npc"],
        expected_location_after="East Alley",
        expect_all_resolved=True,
        expect_blocked_items=False,
        expect_summary=True,
        tags=["inspection", "medium"],
    ),
    MechanicsPhaseCase(
        id="MPHASE-10",
        description="Investigation check on the Frayed Mooring Rope found at the Docks",
        player_input="I examine the frayed mooring rope closely.",
        player_location="Docks",
        intent={
            "action": "inspect", "action_category": "inspect",
            "targets": ["Frayed Mooring Rope"],
        },
        beat_index=2,
        discovered_keys=["Town Square", "Harbor Gate", "Docks"],
        conversation_history=[
            "Player: I look around the docks.",
            "DM: A length of rope near the pier looks darker near one end.",
        ],
        story_status="Bloodstains and unexplained cuts have appeared near the docks.",
        session_summary="Intro: You arrived at dusk.\nRecap: You spotted a suspicious rope at the Docks.",
        todo_items=[
            {"task": "Investigation check on the Frayed Mooring Rope.", "requires_tool": True},
        ],
        todo_summary="Investigation check on the Frayed Mooring Rope.",
        intent_summary="Perform an investigation check on the Frayed Mooring Rope.",
        expected_tools_called=[
            {"name": "skill_check", "args": {"entity_key": "Player", "skill": "investigation"}},
        ],
        should_not_call=["move_to_location", "move_npc"],
        expected_location_after="Docks",
        expect_all_resolved=True,
        expect_blocked_items=False,
        expect_summary=True,
        tags=["inspection", "medium"],
    ),
    MechanicsPhaseCase(
        id="MPHASE-11",
        description="Insight check on Mitch at Town Square",
        player_input="I look Mitch in the eye and try to tell if he's lying.",
        player_location="Town Square",
        intent={
            "action": "inspect", "action_category": "inspect",
            "targets": ["Mitch"],
        },
        beat_index=1,
        discovered_keys=["Town Square"],
        conversation_history=[
            "Player: I approach Mitch.",
            "DM: Mitch's eyes flick away when you mention the bloodstains.",
        ],
        story_status="Mitch is the prime suspect but claims he cannot remember what happened.",
        session_summary="Intro: You arrived at dusk.\nRecap: You spoke with Mitch about the bloodstains.",
        todo_items=[
            {"task": "Insight check on Mitch to detect deception.", "requires_tool": True},
        ],
        todo_summary="Insight check on Mitch.",
        intent_summary="Perform an insight check on Mitch to detect deception.",
        expected_tools_called=[
            {"name": "skill_check", "args": {"entity_key": "Player", "skill": "insight"}},
        ],
        should_not_call=["move_to_location", "move_npc"],
        expected_location_after="Town Square",
        expect_all_resolved=True,
        expect_blocked_items=False,
        expect_summary=True,
        tags=["social", "inspection", "medium"],
    ),
    MechanicsPhaseCase(
        id="MPHASE-12",
        description="Perception check at South Bridge to find the Shattered Lantern Glass evidence",
        player_input="I look around the bridge for anything left behind.",
        player_location="South Bridge",
        intent={
            "action": "inspect", "action_category": "inspect",
            "targets": ["South Bridge"],
        },
        beat_index=2,
        discovered_keys=["Town Square", "South Bridge"],
        conversation_history=[
            "Player: I cross to the South Bridge.",
            "DM: The lantern-lit parapet is quiet, but the stones near the railing look recently scrubbed.",
        ],
        story_status="Witnesses report shouting near the South Bridge on a storm night.",
        session_summary="Intro: You arrived at dusk.\nRecap: You reached the South Bridge following a witness tip.",
        todo_items=[
            {"task": "Perception check to find physical evidence at South Bridge.", "requires_tool": True},
        ],
        todo_summary="Perception check for evidence at South Bridge.",
        intent_summary="Search South Bridge for physical evidence with a perception check.",
        expected_tools_called=[
            {"name": "skill_check", "args": {"entity_key": "Player", "skill": "perception"}},
        ],
        should_not_call=["move_to_location", "move_npc"],
        expected_location_after="South Bridge",
        expect_all_resolved=True,
        expect_blocked_items=False,
        expect_summary=True,
        tags=["inspection", "medium"],
    ),
    MechanicsPhaseCase(
        id="MPHASE-13",
        description="Persuasion check to talk Gate Guard Ren into letting player through",
        player_input="I try to convince Gate Guard Ren to let me through.",
        player_location="Harbor Gate",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Gate Guard Ren"],
        },
        beat_index=2,
        discovered_keys=["Town Square", "Harbor Gate"],
        conversation_history=[
            "Player: I approach Guard Ren at the gate.",
            "DM: Ren eyes you carefully, hand resting on his baton.",
        ],
        story_status="The harbor gate is closed to unauthorized visitors.",
        session_summary="Intro: You arrived at dusk.\nRecap: You reached the Harbor Gate.",
        todo_items=[
            {"task": "Attempt persuasion check to convince Guard Ren.", "requires_tool": True},
        ],
        todo_summary="Persuasion check against Guard Ren.",
        intent_summary="Persuasion check against Guard Ren.",
        expected_tools_called=[
            {"name": "skill_check", "args": {"entity_key": "Player", "skill": "persuasion"}},
        ],
        should_not_call=["move_to_location"],
        expected_location_after="Harbor Gate",
        expect_all_resolved=True,
        expect_blocked_items=False,
        expect_summary=True,
        tags=["social", "medium"],
    ),
    MechanicsPhaseCase(
        id="MPHASE-14", #this one is weird because technically mara is at bar counter location, not copper cup
        description="Multi-step: move to Copper Cup then talk to Mara",
        player_input="I go to the Copper Cup and talk to Mara.",
        player_location="Town Square",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Mara"],
        },
        beat_index=1,
        discovered_keys=["Town Square"],
        session_summary="Intro: You arrived at dusk in the harbor town.",
        todo_items=[
            {"task": "Move player to the Copper Cup.", "requires_tool": True},
            {"task": "Resolve conversation with Mara.", "requires_tool": False},
        ],
        todo_summary="Move to Copper Cup then talk to Mara.",
        intent_summary="Move to Copper Cup then talk to Mara.",
        expected_tools_called=[
            {"name": "move_to_location", "args": {"location_key": "Copper Cup"}},
        ],
        should_not_call=["move_npc"],
        expected_location_after="Copper Cup",
        expect_all_resolved=True,
        expect_blocked_items=False,
        expect_summary=True,
        tags=["social", "medium", "multi-step"],
    ),

    MechanicsPhaseCase(
        id="MPHASE-15",
        description="Attack on NPC with combat skill check",
        player_input="I draw my knife and lunge at Mitch.",
        player_location="Copper Cup",
        intent={
            "action": "attack", "action_category": "attack",
            "targets": ["Mitch"],
        },
        beat_index=2,
        discovered_keys=["Town Square", "Copper Cup"],
        conversation_history=[
            "Player: I confront Mitch.",
            "DM: Mitch shoves aside a stool and reaches for something at his belt.",
        ],
        story_status="Mitch has turned hostile.",
        session_summary="Intro: You arrived at dusk.\nRecap: Mitch turned hostile at the Copper Cup.",
        todo_items=[
            {"task": "Roll attack check against Mitch.", "requires_tool": True},
            {"task": "Apply result to Mitch's state.", "requires_tool": False},
        ],
        todo_summary="Roll attack, then apply result.",
        intent_summary="Roll attack against Mitch and apply result.",
        expected_tools_called=[
            {"name": "skill_check", "args": {"entity_key": "Player"}},
        ],
        should_not_call=["move_to_location"],
        expected_location_after="Copper Cup",
        expect_all_resolved=True,
        expect_blocked_items=False,
        expect_summary=True,
        tags=["attack", "hard"],
    ),
    MechanicsPhaseCase(
        id="MPHASE-16",
        description="Multi-step: move to Old Well then insight check on Old Tellan's story",
        player_input="I go find Old Tellan at the well and listen carefully to what he says.",
        player_location="Market Stalls",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Old Tellan"],
        },
        beat_index=2,
        discovered_keys=["Town Square", "Market Stalls"],
        conversation_history=[
            "Player: I wander through the market stalls.",
            "DM: A vendor mentions Old Tellan has been muttering strange things near the well.",
        ],
        story_status="Old Tellan keeps telling stories that match official incident reports no one should know.",
        session_summary="Intro: You arrived at dusk.\nRecap: You heard about Old Tellan at the market.",
        todo_items=[
            {"task": "Move player to the Old Well.", "requires_tool": True},
            {"task": "Insight check on Old Tellan's account.", "requires_tool": True},
        ],
        todo_summary="Move to Old Well and insight check on Old Tellan.",
        intent_summary="Move to Old Well, then insight check on Old Tellan's story.",
        expected_tools_called=[
            {"name": "move_to_location", "args": {"location_key": "Old Well"}},
            {"name": "skill_check", "args": {"entity_key": "Player", "skill": "insight"}},
        ],
        should_not_call=["move_npc"],
        expected_location_after="Old Well",
        expect_all_resolved=True,
        expect_blocked_items=False,
        expect_summary=True,
        tags=["social", "hard", "multi-step"],
    ),
    MechanicsPhaseCase(
        id="MPHASE-17",
        description="Multi-step: move to Smuggler's Entrance, insight check on Lia, record her reaction",
        player_input="I find Smuggler Lia and show her the rope.",
        player_location="Docks",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Smuggler Lia", "Frayed Mooring Rope"],
        },
        beat_index=3,
        discovered_keys=["Town Square", "Harbor Gate", "Docks"],
        conversation_history=[
            "Player: I search the docks.",
            "DM: Lia is spotted near the Smuggler's Entrance.",
        ],
        story_status="The investigation points toward smuggling activity.",
        session_summary="Intro: You arrived at dusk.\nRecap: You found the rope and located Lia.",
        todo_items=[
            {"task": "Move player to Smuggler's Entrance.", "requires_tool": True},
            {"task": "Insight check on Lia's reaction to the rope.", "requires_tool": True},
            {"task": "Record Lia's reaction as a memory.", "requires_tool": True},
        ],
        todo_summary="Move to Lia, insight check, record reaction.",
        intent_summary="Move to Smuggler's Entrance, insight check on Lia, record her reaction.",
        expected_tools_called=[
            {"name": "move_to_location", "args": {"location_key": "Smuggler's Entrance"}},
            {"name": "skill_check", "args": {"entity_key": "Player", "skill": "insight"}},
            "write_memory_tool",
        ],
        expected_location_after="Smuggler's Entrance",
        expect_all_resolved=True,
        expect_blocked_items=False,
        expect_summary=True,
        tags=["social", "hard", "multi-step"],
    ),
    MechanicsPhaseCase(
        id="MPHASE-18",
        description="Multi-step: move to Watch Barracks, persuasion check on Captain Varr",
        player_input="I go to the Watch Barracks and press Captain Varr on the edited patrol reports.",
        player_location="Town Square",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Captain Varr"],
        },
        beat_index=3,
        discovered_keys=["Town Square", "Watch Barracks"],
        conversation_history=[
            "Player: I look at the Night Patrol Logbook.",
            "DM: Several entries are crossed out and rewritten. Someone altered the records.",
        ],
        story_status="The Night Patrol Logbook shows edited entries. Captain Varr oversees all patrol reports.",
        session_summary="Intro: You arrived at dusk.\nRecap: You found evidence of altered patrol records.",
        todo_items=[
            {"task": "Move player to the Watch Barracks.", "requires_tool": True},
            {"task": "Persuasion check to press Captain Varr on the edited reports.", "requires_tool": True},
            {"task": "Record Varr's response as a memory.", "requires_tool": True},
        ],
        todo_summary="Move to Watch Barracks, persuade Varr, record response.",
        intent_summary="Move to Watch Barracks, persuasion check on Captain Varr, record his response.",
        expected_tools_called=[
            {"name": "move_to_location", "args": {"location_key": "Watch Barracks"}},
            {"name": "skill_check", "args": {"entity_key": "Player", "skill": "persuasion"}},
            "write_memory_tool",
        ],
        expected_location_after="Watch Barracks",
        expect_all_resolved=True,
        expect_blocked_items=False,
        expect_summary=True,
        tags=["social", "hard", "multi-step"],
    ),
    MechanicsPhaseCase(
        id="MPHASE-19",
        description="Multi-step: move to Warehouse Row, investigation check on the Smugglers' Ledger",
        player_input="I search Warehouse Row for anything connecting the cargo gaps to the bloodstains.",
        player_location="Docks",
        intent={
            "action": "inspect", "action_category": "inspect",
            "targets": ["Warehouse Row"],
        },
        beat_index=3,
        discovered_keys=["Town Square", "Harbor Gate", "Docks", "Warehouse Row"],
        conversation_history=[
            "Player: I ask Dockmaster Hara about the missing cargo.",
            "DM: Hara's jaw tightens. The gaps match the same nights no one can account for.",
        ],
        story_status="Cargo discrepancies in Hara's ledger align with the nights of the bloodstains.",
        session_summary="Intro: You arrived at dusk.\nRecap: Hara's ledger gaps match the bloodstain nights.",
        todo_items=[
            {"task": "Move player to Warehouse Row.", "requires_tool": True},
            {"task": "Investigation check on the Smugglers' Ledger.", "requires_tool": True},
            {"task": "Record key findings from the ledger as a memory.", "requires_tool": True},
        ],
        todo_summary="Move to Warehouse Row, investigate the ledger, record findings.",
        intent_summary="Move to Warehouse Row, investigation check on Smugglers' Ledger, record findings.",
        expected_tools_called=[
            {"name": "move_to_location", "args": {"location_key": "Warehouse Row"}},
            {"name": "skill_check", "args": {"entity_key": "Player", "skill": "investigation"}},
            "write_memory_tool",
        ],
        expected_location_after="Warehouse Row",
        expect_all_resolved=True,
        expect_blocked_items=False,
        expect_summary=True,
        tags=["inspection", "hard", "multi-step"],
    ),
    MechanicsPhaseCase(
        id="MPHASE-20",
        description="Multi-step: blocked move of Copper Cup to Temple unreachable, conversation with Serah also fails",
        player_input="I go confront Cleric Serah at the temple about the bloodstains.",
        player_location="Copper Cup",
        intent={
            "action": "talk", "action_category": "talk",
            "targets": ["Cleric Serah"],
        },
        beat_index=3,
        discovered_keys=["Town Square", "Copper Cup"],
        conversation_history=[
            "Player: I ask Mara about the bloodstains.",
            "DM: Mara lowers her voice. Serah at the temple has been treating people with wounds they can't explain.",
        ],
        story_status="Cleric Serah is treating victims of the memory lapses. Evidence increasingly implicates the Temple.",
        session_summary="Intro: You arrived at dusk.\nRecap: Mara pointed you toward Cleric Serah at the temple.",
        todo_items=[
            {"task": "Move player to Temple of the Tide.", "requires_tool": True},
            {"task": "Confront Cleric Serah about the bloodstains and memory lapses.", "requires_tool": False},
        ],
        todo_summary="Move to Temple of the Tide and confront Cleric Serah.",
        intent_summary="Move to Temple of the Tide and confront Cleric Serah.",
        expected_tools_called=[
            {"name": "move_to_location", "args": {"location_key": "Temple of the Tide"}},
        ],
        expected_location_after="Copper Cup",
        expect_all_resolved=True,
        expect_blocked_items=True,
        expect_summary=True,
        tags=["social", "hard", "blocked", "multi-step"],
    ),
]










# ============================================================
# test 4: Narrative Requirement
# ============================================================

@dataclass
class NarrativeRequirementCase:
    id: str
    description: str

    player_input: str
    player_location: str
    intent: Dict[str, Any]
    plan: str
    verdict: str
    notes: str
    beat_index: int = 0
    discovered_keys: List[str] = field(default_factory=list)
    npc_locations: Dict[str, str] = field(default_factory=dict)
    quest_flags: Dict[str, bool] = field(default_factory=dict)
    conversation_history: List[str] = field(default_factory=list)
    action_results: List[Dict] = field(default_factory=list)
    story_status: str = ""
    session_summary: str = ""

    checks: List[str] = field(default_factory=list)
    required_sections: List[str] = field(default_factory=list)
    forbidden_patterns: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


NARRATIVE_REQUIREMENT_CASES: List[NarrativeRequirementCase] = [
    NarrativeRequirementCase(
        id="NAR-01",
        description="Simple move to Copper Cup",
        player_input="I want to go to the Copper Cup.",
        player_location="Copper Cup",
        intent={"action": "move", "targets": ["Copper Cup"]},
        plan="Describe the warm low-beamed tavern: lanterns, stew smell, Mara behind the counter.",
        verdict="approve",
        notes="Movement valid. Copper Cup is adjacent to Town Square.",
        beat_index=0,
        discovered_keys=["Town Square", "Copper Cup"],
        conversation_history=["Player: I want to go to the Copper Cup."],
        action_results=[
            {"name": "move_to_location", "result": {"success": True, "reason": "Moved to Copper Cup."}}
        ],
        session_summary="Intro: You arrived in the harbor town at dusk.",
        checks=[
            "has_two_sections",
            "thoughts_before_narrative",
            "thoughts_is_first_person",
            "second_person",
            "no_explicit_choices",
            "minimum_length",
            "no_player_agency_taken",
            "narrative_no_the_player",
            "narrative_no_bare_i",
            "mentions_current_location",
        ],
        required_sections=[],
        forbidden_patterns=[],
        tags=["movement", "easy"],
    ),
    NarrativeRequirementCase(
        id="NAR-02",
        description="Simple NPC greeting",
        player_input="I say hi to Mara.",
        player_location="Copper Cup",
        intent={"action": "talk", "targets": ["Mara"]},
        plan="Mara greets the player with polite but guarded warmth.",
        verdict="approve",
        notes="Interaction valid. Mara is present.",
        beat_index=0,
        discovered_keys=["Town Square", "Copper Cup"],
        conversation_history=[
            "Player: I walk into the Copper Cup.",
            "DM: The tavern is warm. Mara looks up from behind the counter.",
        ],
        session_summary="Intro: You arrived at dusk.\nRecap: You entered the Copper Cup.",
        checks=[
            "has_two_sections",
            "thoughts_before_narrative",
            "thoughts_is_first_person",
            "second_person",
            "no_explicit_choices",
            "minimum_length",
            "no_player_agency_taken",
            "narrative_no_the_player",
            "narrative_no_bare_i",
            "mentions_current_location",
        ],
        required_sections=[],
        forbidden_patterns=[],
        tags=["social", "easy"],
    ),
    NarrativeRequirementCase(
        id="NAR-03",
        description="Simple blocked movement because of non-adjacency",
        player_input="I head down to the Docks.",
        player_location="Town Square",
        intent={"action": "move", "targets": ["Docks"]},
        plan="Inform the player the Docks are not reachable from here.",
        verdict="revise",
        notes="Movement blocked. Player stays at Town Square.",
        beat_index=0,
        discovered_keys=["Town Square"],
        session_summary="",
        checks=[
            "has_two_sections",
            "thoughts_before_narrative",
            "thoughts_is_first_person",
            "second_person",
            "no_explicit_choices",
            "no_player_agency_taken",
            "narrative_no_the_player",
            "narrative_no_bare_i",
            "mentions_current_location",
            "concise",
        ],
        required_sections=[],
        forbidden_patterns=[],
        tags=["movement", "easy", "blocked"],
    ),
    NarrativeRequirementCase(
        id="NAR-04",
        description="Simple blocked movement because of impossible action",
        player_input="I want to fly up into the air and glide over to the Wizard's House.",
        player_location="Town Square",
        intent={"action": "move", "targets": ["Wizard's House"]},
        plan="Player cannot fly. Refusal: no means of flight exist. Player remains in the Town Square.",
        verdict="revise",
        notes="Action blocked. No flight ability. Player stays at Town Square.",
        beat_index=0,
        discovered_keys=["Town Square"],
        session_summary="Intro: You arrived in the harbor town at dusk.",
        checks=[
            "has_two_sections",
            "thoughts_before_narrative",
            "thoughts_is_first_person",
            "second_person",
            "no_explicit_choices",
            "no_player_agency_taken",
            "narrative_no_the_player",
            "narrative_no_bare_i",
            "mentions_current_location",
            "concise",
        ],
        required_sections=[],
        forbidden_patterns=[
            r"\byou fly\b",
            r"\byou soar\b",
            r"\byou glide\b",
            r"\byou float\b",
        ],
        tags=["movement", "easy", "blocked", "impossible_action"],
    ),
    NarrativeRequirementCase(
        id="NAR-05",
        description="Simple blocked attack action because NPC not there",
        player_input="I draw my knife and lunge at Cleric Serah.",
        player_location="Town Square",
        intent={"action": "attack", "targets": ["Cleric Serah"]},
        plan="Cleric Serah is not in the Town Square. Refusal: target not present, attack cannot proceed.",
        verdict="revise",
        notes="Action blocked. Cleric Serah is at the Temple of the Tide, not here.",
        beat_index=1,
        discovered_keys=["Town Square"],
        conversation_history=[
            "Player: I look around the square.",
            "DM: The cobbled square hums with evening activity. Lanterns flicker above the crowd.",
        ],
        session_summary="Intro: You arrived at dusk.\nRecap: You surveyed the Town Square.",
        checks=[
            "has_two_sections",
            "thoughts_before_narrative",
            "thoughts_is_first_person",
            "second_person",
            "no_explicit_choices",
            "no_player_agency_taken",
            "narrative_no_the_player",
            "narrative_no_bare_i",
            "mentions_current_location",
            "concise",
        ],
        required_sections=[],
        forbidden_patterns=[
            r"serah.{0,40}wound",
            r"serah.{0,40}hit",
        ],
        tags=["attack", "easy", "blocked"],
    ),

    NarrativeRequirementCase(
        id="NAR-06",
        description="Inspection for details about the alley",
        player_input="I look around the alley.",
        player_location="East Alley",
        intent={"action": "inspect", "targets": ["East Alley"]},
        plan="Describe the shadowed alley and dark stains on the cobblestones.",
        verdict="approve",
        notes="Inspection valid.",
        beat_index=2,
        discovered_keys=["Town Square", "East Alley"],
        conversation_history=["Player: I slip into the East Alley to investigate."],
        story_status="The bloodstain investigation is underway.",
        session_summary="Intro: You arrived at dusk.\nRecap: You entered the East Alley.",
        checks=[
            "has_two_sections",
            "thoughts_before_narrative",
            "thoughts_is_first_person",
            "second_person",
            "no_explicit_choices",
            "minimum_length",
            "no_player_agency_taken",
            "narrative_no_the_player",
            "narrative_no_bare_i",
            "mentions_current_location",
        ],
        required_sections=[],
        forbidden_patterns=[],
        tags=["inspection", "medium"],
    ),

    NarrativeRequirementCase(
        id="NAR-07",
        description="conversation with untrusting NPC",
        player_input="I ask Mara about what she knows.",
        player_location="Copper Cup",
        intent={"action": "talk", "targets": ["Mara"]},
        plan="Mara responds guardedly, hinting the upstairs lock uses an anniversary date.",
        verdict="approve",
        notes="Interaction valid. Mara is present.",
        beat_index=1,
        discovered_keys=["Town Square", "Copper Cup"],
        conversation_history=[
            "Player: I walk into the Copper Cup.",
            "DM: The low-beamed tavern is warm. Mara watches from behind the counter.",
            "Player: I ask Mara about what she knows.",
        ],
        story_status="Bloodstains found across town, no missing bodies.",
        session_summary=(
            "Intro: You arrived at dusk, drawn by rumors of bloodstains.\n"
            "Recap: You entered the Copper Cup and approached Mara."
        ),
        checks=[
            "has_two_sections",
            "thoughts_before_narrative",
            "thoughts_is_first_person",
            "second_person",
            "no_explicit_choices",
            "minimum_length",
            "no_player_agency_taken",
            "narrative_no_the_player",
            "narrative_no_bare_i",
            "mentions_current_location",
        ],
        required_sections=[],
        forbidden_patterns=[],
        tags=["social", "medium"],
    ),

    NarrativeRequirementCase(
        id="NAR-08",
        description="Successful skill check result within the plan",
        player_input="I search the alley carefully.",
        player_location="East Alley",
        intent={"action": "inspect", "targets": ["East Alley"]},
        plan="Player succeeded a perception check (DC 14). Describe finding a hidden bloodstained cloth tucked behind a loose brick.",
        verdict="approve",
        notes="Perception check passed. Reveal the hidden clue.",
        beat_index=2,
        discovered_keys=["Town Square", "East Alley"],
        conversation_history=["Player: I search the alley carefully."],
        action_results=[
            {"name": "skill_check", "result": {"success": True, "roll": 17, "dc": 14, "reason": "Perception check passed."}}
        ],
        story_status="The investigation is underway.",
        session_summary="Intro: You arrived at dusk.\nRecap: You are searching the East Alley.",
        checks=[
            "has_two_sections",
            "thoughts_before_narrative",
            "thoughts_is_first_person",
            "second_person",
            "no_explicit_choices",
            "minimum_length",
            "no_player_agency_taken",
            "narrative_no_the_player",
            "narrative_no_bare_i",
        ],
        required_sections=[],
        forbidden_patterns=[],
        tags=["inspection", "medium"],
    ),

    NarrativeRequirementCase(
        id="NAR-09",
        description="Failed skill check narrated with consequences",
        player_input="I try to convince Guard Ren to let me through.",
        player_location="Harbor Gate",
        intent={"action": "talk", "targets": ["Gate Guard Ren"]},
        plan="Player failed persuasion check (DC 13). Ren refuses and becomes suspicious.",
        verdict="approve",
        notes="Persuasion check failed. Ren is now suspicious and watching the player.",
        beat_index=2,
        discovered_keys=["Town Square", "Harbor Gate"],
        conversation_history=[
            "Player: I approach Guard Ren.",
            "DM: Ren eyes you carefully at the gate.",
        ],
        story_status="The harbor gate is restricted.",
        session_summary="Intro: You arrived at dusk.\nRecap: You reached the Harbor Gate.",
        action_results=[
            {"name": "skill_check", "result": {"success": False, "roll": 5, "dc": 13, "reason": "Persuasion check failed."}}
        ],
        checks=[
            "has_two_sections",
            "thoughts_before_narrative",
            "thoughts_is_first_person",
            "second_person",
            "no_explicit_choices",
            "minimum_length",
            "no_player_agency_taken",
            "narrative_no_the_player",
            "narrative_no_bare_i",
        ],
        required_sections=[],
        forbidden_patterns=[],
        tags=["social", "medium"],
    ),
    NarrativeRequirementCase(
        id="NAR-10",
        description="attack attempt on non-reachable NPC",
        player_input="I want to kill Town Wizard Arlen right now.",
        player_location="Town Square",
        intent={"action": "attack", "targets": ["Town Wizard Arlen"]},
        plan="Arlen is not here and is behind guards. Refusal: action blocked - target absent and unreachable. Player stays at Town Square.",
        verdict="revise",
        notes="Action blocked. Arlen is at Wizard's House behind hired guards. Player cannot attack from here.",
        beat_index=2,
        discovered_keys=["Town Square"],
        conversation_history=[
            "Player: I ask around about the wizard.",
            "DM: Locals mutter that Town Wizard Arlen rarely leaves his guarded house off the square.",
            "Player: I want to kill Town Wizard Arlen right now.",
        ],
        story_status="Bloodstains found across town. Suspicion points toward arcane involvement.",
        session_summary="Intro: You arrived at dusk.\nRecap: Locals have pointed you toward the wizard as a person of interest.",
        checks=[
            "has_two_sections",
            "thoughts_before_narrative",
            "thoughts_is_first_person",
            "second_person",
            "no_explicit_choices",
            "no_player_agency_taken",
            "narrative_no_the_player",
            "narrative_no_bare_i",
            "mentions_current_location",
            "concise",
        ],
        required_sections=[],
        forbidden_patterns=[
            r"\byou kill\b",
            r"\byou slay\b",
            r"\barlen.{0,60}dead\b",
            r"\barlen.{0,60}falls\b",
            r"\barlen.{0,60}wound",
        ],
        tags=["attack", "medium", "blocked"],
    ),

    NarrativeRequirementCase(
        id="NAR-11",
        description="Player tries to use a nonexistent item",
        player_input="I pull out my grappling hook and climb up to the storeroom window.",
        player_location="Copper Cup",
        intent={"action": "use", "targets": ["grappling hook"]},
        plan="Player has no grappling hook in their inventory. Refusal: item not found. Action cannot proceed.",
        verdict="revise",
        notes="Action blocked. Grappling hook not in player inventory.",
        beat_index=1,
        discovered_keys=["Town Square", "Copper Cup"],
        conversation_history=[
            "Player: I walk into the Copper Cup.",
            "DM: The low-beamed tavern is warm and busy. Mara watches from behind the counter.",
            "Player: I pull out my grappling hook and climb up to the storeroom window.",
        ],
        session_summary="Intro: You arrived at dusk.\nRecap: You entered the Copper Cup and are looking for a way upstairs.",
        checks=[
            "has_two_sections",
            "thoughts_before_narrative",
            "thoughts_is_first_person",
            "second_person",
            "no_explicit_choices",
            "no_player_agency_taken",
            "narrative_no_the_player",
            "narrative_no_bare_i",
            "mentions_current_location",
            "concise",
        ],
        required_sections=[],
        forbidden_patterns=[
            r"\byou reach.{0,30}window",
            r"\byou get to.{0,30}window",
        ],
        tags=["item_use", "medium", "blocked"],
    ),
    NarrativeRequirementCase(
        id="NAR-12",
        description="Attack with reesulting consequences",
        player_input="I draw my knife and lunge at Mitch.",
        player_location="Copper Cup",
        intent={"action": "attack", "targets": ["Mitch"]},
        plan="Attack roll succeeded (DC 12). Mitch is wounded, the tavern erupts into chaos.",
        verdict="approve",
        notes="Attack succeeded. Mitch wounded. NPCs in the tavern react.",
        beat_index=2,
        discovered_keys=["Town Square", "Copper Cup"],
        conversation_history=[
            "Player: I confront Mitch.",
            "DM: Mitch shoves a stool aside, his hand going for his belt.",
            "Player: I draw my knife and lunge at Mitch.",
        ],
        story_status="Mitch has turned hostile at the Copper Cup.",
        session_summary="Intro: You arrived at dusk.\nRecap: Confrontation with Mitch turned violent.",
        action_results=[
            {"name": "skill_check", "result": {"success": True, "roll": 15, "dc": 12, "reason": "Attack succeeded."}}
        ],
        checks=[
            "has_two_sections",
            "thoughts_before_narrative",
            "thoughts_is_first_person",
            "second_person",
            "no_explicit_choices",
            "minimum_length",
            "no_player_agency_taken",
            "narrative_no_the_player",
            "narrative_no_bare_i",
        ],
        required_sections=[],
        forbidden_patterns=[],
        tags=["attack", "medium"],
    ),
    NarrativeRequirementCase(
        id="NAR-13",
        description="Multi-step: succesful move then talked with NPC reaction",
        player_input="I go to the Copper Cup and talk to Mara.",
        player_location="Copper Cup",
        intent={"action": "talk", "targets": ["Mara"]},
        plan="Player moved to Copper Cup successfully and spoke with Mara, who hinted at the lock date.",
        verdict="approve",
        notes="Move succeeded. Mara provided a partial clue about the date lock.",
        beat_index=1,
        discovered_keys=["Town Square", "Copper Cup"],
        conversation_history=[
            "Player: I go to the Copper Cup and talk to Mara.",
        ],
        story_status="Bloodstains found across town with no missing bodies.",
        session_summary="Intro: You arrived at dusk.\nRecap: You made your way to the Copper Cup.",
        action_results=[
            {"name": "move_to_location", "result": {"success": True, "reason": "Moved to Copper Cup."}},
        ],
        checks=[
            "has_two_sections",
            "thoughts_before_narrative",
            "thoughts_is_first_person",
            "second_person",
            "no_explicit_choices",
            "minimum_length",
            "no_player_agency_taken",
            "narrative_no_the_player",
            "narrative_no_bare_i",
        ],
        required_sections=[],
        forbidden_patterns=[],
        tags=["social", "movement", "hard", "multi-step"],
    ),

    NarrativeRequirementCase(
        id="NAR-14",
        description="Multi-step: moved then talked with NPC, but blocked movement",
        player_input="I go confront Cleric Serah at the temple about the bloodstains.",
        player_location="Town Square",
        intent={"action": "talk", "targets": ["Cleric Serah"]},
        plan="Player could not reach the Temple of the Tide from Town Square. Narrate the failed attempt with a sense of urgency.",
        verdict="revise",
        notes="Move blocked. Temple not adjacent. Player remains at Town Square with growing unease.",
        beat_index=3,
        discovered_keys=["Town Square"],
        conversation_history=[
            "Player: I look for a way to reach the temple.",
            "DM: The temple district is on the far side of town, past the harbor.",
        ],
        story_status="Evidence has implicated the Temple of the Tide in the bloodstain mystery.",
        session_summary=(
            "Intro: You arrived at dusk, drawn by rumors of bloodstains.\n"
            "Recap: Clues from the ledger and Mara's hints point toward the temple and Cleric Serah."
        ),
        checks=[
            "has_two_sections",
            "thoughts_before_narrative",
            "thoughts_is_first_person",
            "second_person",
            "no_explicit_choices",
            "no_player_agency_taken",
            "narrative_no_the_player",
            "narrative_no_bare_i",
            "mentions_current_location",
        ],
        required_sections=[],
        forbidden_patterns=[],
        tags=["social", "movement", "hard", "multi-step", "blocked"],
    ),

    NarrativeRequirementCase(
        id="NAR-15",
        description="Multi-step: blocked movement action for investigation action to find NPC to attack them",
        player_input="I sprout wings and fly across the harbor to find Cleric Serah, then stab her before she can speak.",
        player_location="Docks",
        intent={"action": "attack", "targets": ["Cleric Serah"]},
        plan="Multiple refusals: player cannot fly, Cleric Serah is at the Temple of the Tide not the Docks, and unprovoked murder of a key NPC is blocked. Player stays at the Docks. Narrate the refusal with atmosphere without being preachy.",
        verdict="revise",
        notes="Action fully blocked. No flight, Serah absent, violence against key NPC refused. Player remains at Docks.",
        beat_index=3,
        discovered_keys=["Town Square", "Harbor Gate", "Docks"],
        conversation_history=[
            "Player: I ask the dockworkers about the bloodstains.",
            "DM: Deckhand Finn lowers his voice and says the stains appeared near the pump well after a storm night.",
            "Player: I talk to Dockmaster Hara about missing cargo.",
            "DM: Hara flips open her ledger, her jaw tight. The gaps match the nights no one can account for.",
            "Player: I sprout wings and fly across the harbor to find Cleric Serah, then stab her before she can speak.",
        ],
        story_status="Dockside witnesses confirm recurring gaps in memory tied to the same hours. Temple involvement suspected.",
        session_summary=(
            "Intro: You arrived at dusk chasing rumors of bloodstains.\n"
            "Recap: Finn and Hara both confirmed gaps in the dockside ledgers matching the nights of the stains."
        ),
        checks=[
            "has_two_sections",
            "thoughts_before_narrative",
            "thoughts_is_first_person",
            "second_person",
            "no_explicit_choices",
            "no_player_agency_taken",
            "narrative_no_the_player",
            "narrative_no_bare_i",
            "mentions_current_location",
            "concise",
        ],
        required_sections=[],
        forbidden_patterns=[
            r"\byou fly\b",
            r"\byou soar\b",
            r"\byou sprout\b",
            r"\byou stab\b",
            r"serah.{0,60}wound",
            r"serah.{0,60}dead",
            r"serah.{0,60}falls",
        ],
        tags=["movement", "investigation", "attack", "multi-step", "blocked", "hard"],
    ),
]


__all__ = [
    "IntentCase", "INTENT_CASES",
    "IntentPhaseCase", "INTENT_PHASE_CASES",
    "MechanicsPhaseCase", "MECHANICS_PHASE_CASES",
    "NarrativeRequirementCase", "NARRATIVE_REQUIREMENT_CASES",
]
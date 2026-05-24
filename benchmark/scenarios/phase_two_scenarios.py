"""
==============================
PHASE TWO BENCHMARK SCENARIOS
==============================

These cases exercise Phase 2: the write phase. By the time Phase 2
runs, Phase 1 has produced a turn_summary and a plan, the narrator
has produced prose, and now the orchestrator must commit the right
mutations to the world: move the player, move NPCs and items, write
the memories that justify future recall.

The scorer has two layers here.

    function_calls   the closed-world set of write tools the model
                     called (move_to_location, move_npc, move_world_item,
                     write_memory_tool, plus the implicit finalize_writes)

    state_changes    the actual mutations to the GameState snapshot:
                     player_location, npc_locations, visited_keys,
                     discovered_keys, quest_flags, and which entities
                     had memory lines written. This catches the case
                     where the model called the right tool with the
                     wrong arguments and changed nothing.

The cases progress from easy to hard:

    EASY    one clean mutation: move into an adjacent room and write
            a memory; greet someone and write paired memories.

    MEDIUM  inventory shuffles (pick up an item, move_world_item to
            the player), skill-check follow-through, gracefully
            handled blocks that still record a memory of the attempt.

    HARD    multi-mutation turns: enter a new room and pick up an
            item in the same turn; confrontations that write memories
            on player, NPC, and location; code-clue payoffs that
            change a quest flag and a location memory together.

No 4th-wall meta turns. Every scenario is a thing the character does.
"""
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
    #
    # Player location is treated as expected to be `expected_location_after`
    # after the turn (which may equal `player_location` meaning "no change").
    #
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

    # ------------------------------------------------------------------
    # EASY: one clean mutation, baseline memory writes.
    # ------------------------------------------------------------------

    PhaseTwoCase(
        id="P2-01",
        description="Move into an adjacent room; write a memory and mark visited",
        player_input="I push through the door of the Copper Cup",
        player_location="Town Square",
        turn_summary="Player walked from Town Square into the Copper Cup tavern.",
        narration_focus="Arrival at the Copper Cup.",
        blocked_reason="",
        narration=(
            "Thoughts: The square's noise fades behind the door; the warmth wraps in.\n"
            "Narrative: You push through the heavy door of the Copper Cup. The warm light "
            "and smell of malt wrap around you as you step inside."
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
        description=(
            "Greet an NPC in the same room. Light conversation, paired "
            "memory writes for the speaker and the listener; no movement."
        ),
        player_input="I catch Jorin's eye and ask how the square has been today",
        player_location="Town Square",
        npc_locations={"Street Performer Jorin": "Town Square"},
        turn_summary=(
            "Player greeted Street Performer Jorin in Town Square and asked how the "
            "day has been. Jorin offered a brief, performer-bright answer."
        ),
        narration_focus="A short exchange. Jorin tosses a stone, smiles, gives a tiny piece of gossip.",
        blocked_reason="",
        narration=(
            "Thoughts: Jorin is the kind of man who notices everything while pretending to notice nothing.\n"
            "Narrative: Jorin's hand goes still on the painted stone he is juggling. 'Slow,' he says, "
            "smile small. 'Folks aren't lingering tonight.'"
        ),
        expect_finalize_writes=True,
        expected_tools_called=["write_memory_tool"],
        expected_location_after="Town Square",
        expected_memory_writes=["Street Performer Jorin", "Player"],
        tags=["social", "memory", "easy"],
    ),

    PhaseTwoCase(
        id="P2-03",
        description=(
            "Ask Mara about a topic in her seeded memory. Paired memory "
            "writes (player, Mara, and the location of the exchange)."
        ),
        player_input="I lean across the bar and ask Mara if anyone has been fiddling with the storeroom lock lately",
        player_location="Copper Cup",
        npc_locations={"Mara": "Copper Cup"},
        turn_summary=(
            "Player asked Mara about the storeroom lock. Mara, recognizing the question "
            "from her own worries, admitted the lock has been tested but did not share the code."
        ),
        narration_focus="Mara's reluctant answer; eyes flicking to the staircase.",
        blocked_reason="",
        narration=(
            "Thoughts: Mara has been waiting for someone to notice. She is not ready to say everything.\n"
            "Narrative: Mara stops polishing the cup. 'Someone has,' she says quietly. 'More than once. "
            "I do not know who.' Her eyes flick to the stair landing."
        ),
        phase_one_tool_calls=[
            {"phase": "phase_one", "name": "retrieve_memory_tool",
             "arguments": {"entity_name": "Mara"},
             "result": {"ok": True, "memories": [
                 "Mara keeps the storeroom code private and knows someone has tested the lock repeatedly."
             ]}},
        ],
        expect_finalize_writes=True,
        expected_tools_called=["write_memory_tool"],
        expected_location_after="Copper Cup",
        expected_memory_writes=["Mara", "Player"],
        tags=["social", "memory_recall", "easy"],
    ),

    # ------------------------------------------------------------------
    # MEDIUM: inventory shuffles, mechanics follow-through, soft blocks.
    # ------------------------------------------------------------------

    PhaseTwoCase(
        id="P2-04",
        description=(
            "Pick up an item that lives at the current location. The "
            "item should change holder from the location to the Player "
            "via move_world_item, and a memory line should anchor the "
            "find on both the player and the location."
        ),
        player_input="I pick up the cracked spyglass and tuck it into my coat",
        player_location="Harbor Gate",
        conversation_history=[
            "I look around the gate.",
            "A cracked spyglass lies forgotten on the stone ledge by the guardpost.",
        ],
        turn_summary=(
            "Player took the Cracked Spyglass from the stone ledge at Harbor Gate and "
            "pocketed it. The spyglass now belongs to the player."
        ),
        narration_focus="Brass weight in the hand, hairline crack across the lens, etched town crest.",
        blocked_reason="",
        narration=(
            "Thoughts: It will fit inside your coat without anyone noticing.\n"
            "Narrative: The brass is heavier than it looks. The crack catches the lantern light "
            "as you slip it under your coat."
        ),
        phase_one_tool_calls=[
            {"phase": "phase_one", "name": "check_can_interact",
             "arguments": {"entity_key": "Cracked Spyglass"},
             "result": {"ok": True, "can_interact": True, "entity_type": "item"}},
        ],
        expect_finalize_writes=True,
        expected_tools_called=["move_world_item", "write_memory_tool"],
        expected_location_after="Harbor Gate",
        expected_memory_writes=["Player", "Harbor Gate"],
        tags=["item", "inventory", "medium"],
    ),

    PhaseTwoCase(
        id="P2-05",
        description=(
            "Successful stealth past Gate Guard Ren. No movement this turn "
            "(success at the check itself is the event); a memory should "
            "record the close call on the player."
        ),
        player_input="I time my steps with the lantern shadow and try to slip past Ren without him seeing me",
        player_location="Harbor Gate",
        npc_locations={"Gate Guard Ren": "Harbor Gate"},
        turn_summary="Player slipped past Gate Guard Ren unseen. Stealth check succeeded, roll 17 vs DC 14.",
        narration_focus="Tension, quiet steps, success.",
        blocked_reason="",
        narration=(
            "Thoughts: The guard's attention is elsewhere; this is the moment.\n"
            "Narrative: You ease past the lantern's edge of light. Ren's gaze drifts across the "
            "cobbles, never quite finding you."
        ),
        action_tool_calls=[
            {"phase": "phase_one", "name": "skill_check",
             "arguments": {"entity_key": "Player", "skill": "stealth", "dc": 14},
             "result": {"ok": True, "success": True, "roll": 17, "total": 17, "dc": 14}},
        ],
        expect_finalize_writes=True,
        expected_tools_called=["write_memory_tool"],
        expected_location_after="Harbor Gate",
        expected_memory_writes=["Player", "Harbor Gate"],
        tags=["mechanics", "memory", "medium"],
    ),

    PhaseTwoCase(
        id="P2-06",
        description=(
            "Blocked movement. Phase 1 reported that the Smuggler's "
            "Entrance is not reachable from Town Square. Phase 2 must "
            "NOT move the player; it should still write a memory of "
            "the attempt so the player's intent persists."
        ),
        player_input="I head straight down to the Smuggler's Entrance under the warehouses",
        player_location="Town Square",
        turn_summary="Player tried to walk directly to the Smuggler's Entrance from Town Square; not reachable from here.",
        narration_focus="The path constraint surfaced through scene cues.",
        blocked_reason="Smuggler's Entrance is not directly reachable from Town Square.",
        narration=(
            "Thoughts: You will need to come at it from the warehouses or from down by the old well.\n"
            "Narrative: You glance toward the south side of the square. The entrance lies further on; "
            "you cannot step to it from where you stand."
        ),
        expect_finalize_writes=True,
        expected_tools_called=["write_memory_tool"],
        expected_location_after="Town Square",
        expected_memory_writes=["Player"],
        tags=["movement", "blocked", "medium"],
    ),

    PhaseTwoCase(
        id="P2-07",
        description=(
            "Compound turn: move into Back Door - Copper Cup AND interact "
            "with Cook Brenna there. Player moves; Brenna and Player gain "
            "memories of the exchange; the new room is added to visited."
        ),
        player_input="I slip out the back door of the tavern and ask Brenna if she has noticed anything strange",
        player_location="Copper Cup",
        npc_locations={"Cook Brenna": "Back Door - Copper Cup"},
        visited_keys=["Town Square", "Copper Cup"],
        turn_summary=(
            "Player stepped out the back door of the tavern into the alley and asked Cook Brenna "
            "whether she had noticed anything strange. Brenna mentioned seeing Mitch pacing here "
            "before dawn twice this week."
        ),
        narration_focus=(
            "The alley air, the kitchen warmth at Brenna's back, her reluctance to make this a real story."
        ),
        blocked_reason="",
        narration=(
            "Thoughts: Brenna has been waiting for someone she could tell.\n"
            "Narrative: Brenna wipes her hands on her apron. 'Mitch,' she says, voice low. "
            "'Pacing right out there, before sunrise. Twice this week.'"
        ),
        phase_one_tool_calls=[
            {"phase": "phase_one", "name": "check_can_interact",
             "arguments": {"entity_key": "Back Door - Copper Cup"},
             "result": {"ok": True, "can_interact": True, "entity_type": "location"}},
        ],
        expect_finalize_writes=True,
        expected_tools_called=["move_to_location", "write_memory_tool"],
        expected_location_after="Back Door - Copper Cup",
        expected_visited_added=["Back Door - Copper Cup"],
        expected_discovered_added=["Storeroom Door"],
        expected_memory_writes=["Cook Brenna", "Back Door - Copper Cup", "Player"],
        tags=["movement", "social", "compound", "hard"],
    ),

    PhaseTwoCase(
        id="P2-08",
        description=(
            "Confrontation: throw off-scene evidence at an in-scene NPC. "
            "Player remains in the square; memories should be written on "
            "the player, on Mitch (the confrontation lands on him), and "
            "on the location where it happened."
        ),
        player_input=(
            "I plant myself in front of Mitch and tell him Brenna saw him pacing the back door before dawn. "
            "I want to see his face when he hears it."
        ),
        player_location="Town Square",
        npc_locations={"Mitch": "Town Square"},
        visited_keys=["Town Square", "Copper Cup", "Back Door - Copper Cup"],
        conversation_history=[
            "Brenna told me Mitch was pacing the back door before sunrise twice this week.",
            "I head back to the square.",
            "Mitch is still where you left him, hands shaking.",
        ],
        turn_summary=(
            "Player confronted Mitch in Town Square with Cook Brenna's account of him "
            "pacing the back door of the tavern before dawn. Mitch went pale and did not "
            "deny it cleanly; his haunted state showed."
        ),
        narration_focus="The moment Brenna's name lands. End on Mitch's reaction, not the player's next move.",
        blocked_reason="",
        narration=(
            "Thoughts: He is not surprised to hear it. He is surprised someone says it aloud.\n"
            "Narrative: Mitch's jaw works. The square's noise keeps moving around him, but a small "
            "space opens between you. 'Brenna,' he says, half a question, half a wound."
        ),
        phase_one_tool_calls=[
            {"phase": "phase_one", "name": "retrieve_memory_tool",
             "arguments": {"entity_name": "Cook Brenna"},
             "result": {"ok": True, "memories": [
                 "Brenna hears every argument near the back door and noticed Mitch pacing there before dawn twice this week."
             ]}},
            {"phase": "phase_one", "name": "check_can_interact",
             "arguments": {"entity_key": "Mitch"},
             "result": {"ok": True, "can_interact": True, "entity_type": "npc"}},
        ],
        expect_finalize_writes=True,
        expected_tools_called=["write_memory_tool"],
        expected_location_after="Town Square",
        expected_memory_writes=["Mitch", "Town Square", "Player"],
        tags=["social", "confrontation", "memory_chain", "hard"],
    ),

    PhaseTwoCase(
        id="P2-09",
        description=(
            "Code-clue payoff. Player dials the storeroom code 0415, "
            "correctly recalled from the Hidden Scrap and Brin's "
            "anniversary. Memory lines on the Storeroom Door itself "
            "and on the player anchor the unlock so future turns can "
            "recall that the lock was opened. No room change yet; "
            "the door is unlatched but not entered."
        ),
        player_input="I crouch by the storeroom door and dial the brass combination to 0415",
        player_location="Stair Landing",
        visited_keys=["Town Square", "Copper Cup", "Bar Counter", "Stair Landing"],
        conversation_history=[
            "Hidden Scrap: 'cellar restock / upstairs lock is our wedding anniversary date'.",
            "Brin: 'April fifteenth, I think.'",
            "I head up to the stair landing.",
        ],
        turn_summary=(
            "Player dialed 0415 on the storeroom door at the top of the stair landing. "
            "The code is correct; the lock disengaged. The door is unlatched but not yet opened."
        ),
        narration_focus="Careful dials, the small mechanical surrender of the lock.",
        blocked_reason="",
        narration=(
            "Thoughts: The fourth dial settles into place with the others.\n"
            "Narrative: The brass dials turn under your fingers, one click each, until the last "
            "one settles. A soft mechanical sigh; the lock gives."
        ),
        phase_one_tool_calls=[
            {"phase": "phase_one", "name": "check_can_interact",
             "arguments": {"entity_key": "Storeroom Door"},
             "result": {"ok": True, "can_interact": True, "entity_type": "location"}},
        ],
        expect_finalize_writes=True,
        expected_tools_called=["write_memory_tool"],
        expected_location_after="Stair Landing",
        expected_memory_writes=["Storeroom Door", "Player", "Stair Landing"],
        tags=["item", "code_clue", "hard"],
    ),

    PhaseTwoCase(
        id="P2-10",
        description=(
            "Hand off a clue to an NPC. Player gives the Cracked Spyglass "
            "to Captain Varr. move_world_item should reassign the item "
            "from Player to Varr; memory lines on player and Varr should "
            "anchor the handoff. No movement."
        ),
        player_input="I unwrap the cracked spyglass and hand it to Captain Varr",
        player_location="Watch Barracks",
        npc_locations={"Captain Varr": "Watch Barracks"},
        conversation_history=[
            "I picked up the cracked spyglass at the harbor gate earlier.",
            "I went looking for Varr at the watch barracks.",
        ],
        turn_summary=(
            "Player handed the Cracked Spyglass over to Captain Varr in the Watch Barracks. "
            "Varr now holds the item; the player no longer carries it."
        ),
        narration_focus="A small formal exchange between civilian and officer.",
        blocked_reason="",
        narration=(
            "Thoughts: Varr will recognize the etching faster than you would.\n"
            "Narrative: Varr takes the spyglass in two hands. His thumb finds the hairline crack "
            "and the small town crest, and his expression hardens."
        ),
        phase_one_tool_calls=[
            {"phase": "phase_one", "name": "check_can_interact",
             "arguments": {"entity_key": "Captain Varr"},
             "result": {"ok": True, "can_interact": True, "entity_type": "npc"}},
        ],
        expect_finalize_writes=True,
        expected_tools_called=["move_world_item", "write_memory_tool"],
        expected_location_after="Watch Barracks",
        expected_memory_writes=["Captain Varr", "Player", "Watch Barracks"],
        tags=["item", "social", "handoff", "hard"],
    ),
]


__all__ = ["PhaseTwoCase", "PHASE_TWO_CASES"]
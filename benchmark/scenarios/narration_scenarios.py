"""
==============================
NARRATION BENCHMARK SCENARIOS
==============================

These cases exercise the Narrator: the prose phase that runs after
Phase 1 has decided what happened and before Phase 2 writes anything
back to the world. The narrator does not call tools and does not
mutate state; it produces a Thoughts block and a Narrative block in
second-person, present-tense, and keeps the fiction intact.

The cases are arranged from easy to hard:

    EASY    standard movement, brief greetings, simple item beats.
            The checks here are structural (two sections, second
            person, no agency taken from the player, etc.).

    MEDIUM  conversations that should reflect a retrieved memory,
            successful skill checks, and gracefully-handled blocks
            where the narrator must redirect without breaking the
            illusion or using error language.

    HARD    returning to a previously visited place so the prose can
            evoke remembered detail, and confrontations whose weight
            depends on what the narrator was told about prior events.

Every input is in-character. The narrator is graded on whether the
prose obeys the structural rules and avoids the forbidden patterns.
"""
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

    # ------------------------------------------------------------------
    # EASY: structural baseline.
    # ------------------------------------------------------------------

    NarrationCase(
        id="NAR-01",
        description="Standard arrival narration into the tavern",
        player_input="I push through the door of the Copper Cup",
        player_location="Copper Cup",
        visited_keys=["Town Square", "Copper Cup"],
        turn_summary="Player moved from Town Square into the Copper Cup tavern.",
        narration_focus=(
            "Describe the arrival at the Copper Cup. Warm lamplight, the smell of stew "
            "and salt, the regulars at the bar, Mara behind the counter."
        ),
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
        description="Brief in-character greeting; no event, short narration",
        player_input="I tip my chin to Jorin as I pass through the square",
        player_location="Town Square",
        npc_locations={"Street Performer Jorin": "Town Square"},
        turn_summary="Player nodded to Jorin in passing; no real exchange.",
        narration_focus="A small acknowledgement. Keep the scene moving; do not invent dialogue.",
        blocked_reason="",
        checks=[
            "has_two_sections",
            "thoughts_before_narrative",
            "second_person",
            "no_explicit_choices",
            "concise:150",
            "no_player_agency_taken",
        ],
        tags=["social", "trivial", "easy"],
    ),

    NarrationCase(
        id="NAR-03",
        description="Examining an item the scene already surfaced",
        player_input="I pick up the cracked spyglass and turn it over in the light",
        player_location="Harbor Gate",
        conversation_history=[
            "I look around the gate.",
            "A cracked spyglass lies forgotten on the stone ledge by the guardpost.",
        ],
        turn_summary=(
            "Player examines the cracked spyglass. The hairline fracture is real; "
            "tiny etchings on the barrel match the town crest."
        ),
        narration_focus=(
            "Let the player feel the weight of the brass, notice the crest etchings, "
            "and catch the salt-oil smell. Do not advance the plot for them."
        ),
        blocked_reason="",
        phase_one_tool_calls=[
            {"phase": "phase_one", "name": "check_can_interact",
             "arguments": {"entity_key": "Cracked Spyglass"},
             "result": {"ok": True, "can_interact": True, "entity_type": "item"}},
        ],
        checks=_BASE_CHECKS,
        forbidden_patterns=[r"(?i)what would you like", r"(?i)please choose"],
        tags=["item", "inspection", "easy"],
    ),

    # ------------------------------------------------------------------
    # MEDIUM: prose must respect retrieved context and mechanics.
    # ------------------------------------------------------------------

    NarrationCase(
        id="NAR-04",
        description=(
            "Conversation that should reflect Mara's seeded memory about the "
            "storeroom lock being tested. The narrator was given the memory "
            "and should color her words with reluctant recognition without "
            "stating mechanics."
        ),
        player_input="I lean across the bar and ask Mara if anyone has been fiddling with the storeroom lock lately",
        player_location="Copper Cup",
        npc_locations={"Mara": "Copper Cup"},
        turn_summary=(
            "Player asked Mara about the storeroom lock. Mara recognizes the question; "
            "she has noticed the lock being tested repeatedly and keeps the code private."
        ),
        narration_focus=(
            "Show Mara weighing whether to trust the player. Let her admit the lock has "
            "been bothered, but not what the code is. Small gestures over speeches."
        ),
        blocked_reason="",
        phase_one_tool_calls=[
            {"phase": "phase_one", "name": "retrieve_memory_tool",
             "arguments": {"entity_name": "Mara"},
             "result": {"ok": True, "memories": [
                 "Mara keeps the storeroom code private and knows someone has tested the lock repeatedly."
             ]}},
        ],
        checks=_BASE_CHECKS + ["mentions_current_location"],
        forbidden_patterns=[r"(?i)\bnumber\s+\d+", r"(?i)what would you like", r"\b0415\b"],
        tags=["social", "memory", "medium"],
    ),

    NarrationCase(
        id="NAR-05",
        description="Narration after a successful stealth check at the gate",
        player_input="I time my steps with the lantern shadow and try to slip past Ren without him seeing me",
        player_location="Harbor Gate",
        npc_locations={"Gate Guard Ren": "Harbor Gate"},
        turn_summary="Player attempted to sneak past Gate Guard Ren. Stealth succeeded, roll 17 vs DC 14.",
        narration_focus="Tension, quiet steps, success. The guard's gaze drifts but never quite finds you.",
        blocked_reason="",
        action_tool_calls=[
            {"phase": "phase_one", "name": "skill_check",
             "arguments": {"entity_key": "Player", "skill": "stealth", "dc": 14},
             "result": {"ok": True, "success": True, "roll": 17, "total": 17, "dc": 14}},
        ],
        checks=_BASE_CHECKS,
        forbidden_patterns=[r"(?i)roll\s+(a|an|your)", r"(?i)provide\s+your\s+(bonus|modifier)", r"\bDC\s*\d"],
        tags=["mechanics", "skill_check", "medium"],
    ),

    NarrationCase(
        id="NAR-06",
        description="Blocked movement narrated as a soft redirect",
        player_input="I head straight down to the Smuggler's Entrance under the warehouses",
        player_location="Town Square",
        turn_summary=(
            "Player tried to walk directly to the Smuggler's Entrance. That entrance "
            "is hidden under the warehouses and is not reachable from the square."
        ),
        narration_focus=(
            "Acknowledge the intent and surface the constraint through the scene "
            "itself: the square ends here, the entrance lies past the harbor gate "
            "or down by the old well. Do not use the word blocked."
        ),
        blocked_reason="Smuggler's Entrance is not directly reachable from Town Square.",
        checks=_BASE_CHECKS,
        forbidden_patterns=[r"(?i)\berror\b", r"(?i)\bblocked\b", r"(?i)\binvalid\b"],
        tags=["movement", "blocked", "medium"],
    ),

    # ------------------------------------------------------------------
    # HARD: prose that depends on recalled memory and emotional weight.
    # ------------------------------------------------------------------

    NarrationCase(
        id="NAR-07",
        description=(
            "Returning to a previously visited location. The narrator should "
            "color the arrival with what the player saw here before (the "
            "loose brick Pip indicated) without inventing brand-new facts."
        ),
        player_input="I head back into East Alley and crouch where Pip showed me the loose brick",
        player_location="East Alley",
        visited_keys=["Town Square", "East Alley"],
        conversation_history=[
            "I follow Pip into East Alley.",
            "Pip crouches by a loose brick at knee height and grins before slipping away.",
            "I head back toward the square.",
            "I want to return to that brick.",
        ],
        turn_summary=(
            "Player returned to East Alley to revisit the loose brick Pip indicated "
            "on an earlier visit."
        ),
        narration_focus=(
            "The alley should feel familiar this time, not freshly described. "
            "Let the prose recall Pip's grin and the brick's position without "
            "narrating what is behind it yet."
        ),
        blocked_reason="",
        phase_one_tool_calls=[
            {"phase": "phase_one", "name": "retrieve_memory_tool",
             "arguments": {"entity_name": "East Alley"},
             "result": {"ok": True, "memories": [
                 "The player followed Pip here and saw the urchin crouch by a loose brick at knee height."
             ]}},
        ],
        checks=_BASE_CHECKS + ["mentions_current_location"],
        forbidden_patterns=[r"(?i)for the first time", r"(?i)you have never"],
        tags=["movement", "location_memory", "hard"],
    ),

    NarrationCase(
        id="NAR-08",
        description=(
            "Confrontation with Mitch using Brenna's testimony. The narrator "
            "has been told what Brenna said and what Mitch's haunted state is "
            "like. Prose should land with weight but never decide Mitch's "
            "answer for the player."
        ),
        player_input=(
            "I plant myself in front of Mitch and tell him Brenna saw him pacing the back door before dawn. "
            "I want to see his face when he hears it."
        ),
        player_location="Town Square",
        npc_locations={"Mitch": "Town Square"},
        visited_keys=["Town Square", "Copper Cup", "Back Door - Copper Cup"],
        turn_summary=(
            "Player confronted Mitch in the square with what Cook Brenna said about him "
            "pacing the back door of the tavern before dawn. Mitch is fragile and prone "
            "to denial; his story is known to shift under pressure."
        ),
        narration_focus=(
            "Mitch's body language and breath, the moment Brenna's name lands, the "
            "way the square's noise keeps moving while a small space opens around them. "
            "End on Mitch's reaction; do not script what the player does next."
        ),
        blocked_reason="",
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
        checks=_BASE_CHECKS + ["mentions_current_location"],
        forbidden_patterns=[r"(?i)you decide to", r"(?i)you choose to", r"(?i)\berror\b"],
        tags=["social", "confrontation", "memory_chain", "hard"],
    ),

    NarrationCase(
        id="NAR-09",
        description=(
            "Code-clue payoff at the storeroom door. The narrator has the "
            "code in the focus, the player remembered it themselves, and "
            "the prose should let the dials click without taking the next "
            "action for the player."
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
        turn_summary=(
            "Player dialed 0415 on the storeroom door's combination lock. The code is correct; "
            "the lock disengages but the door has not yet been opened."
        ),
        narration_focus=(
            "Quiet hallway, careful dials, the small mechanical surrender of the lock. "
            "Stop on the unlatched door; do not push it open for the player."
        ),
        blocked_reason="",
        phase_one_tool_calls=[
            {"phase": "phase_one", "name": "check_can_interact",
             "arguments": {"entity_key": "Storeroom Door"},
             "result": {"ok": True, "can_interact": True, "entity_type": "location"}},
        ],
        checks=_BASE_CHECKS,
        forbidden_patterns=[r"(?i)you open the door", r"(?i)you step inside", r"(?i)\bDC\s*\d"],
        tags=["item", "code_clue", "hard"],
    ),
]


__all__ = ["NarrationCase", "NARRATION_CASES"]
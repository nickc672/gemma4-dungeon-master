from __future__ import annotations

import unittest

from orchestrator.llm_interaction.prompt_builders import PromptState, build_agent_prompt
from orchestrator.runtime_flow.reconciliation import (
    build_story_status,
    build_turn_memory_entry,
    diff_runtime_state,
)


class TurnReconciliationTests(unittest.TestCase):
    def test_build_story_status_includes_location_and_summary(self) -> None:
        status = build_story_status(
            "Harbor Gate",
            "Asked Ren what it takes to reach the docks.",
            "",
        )
        self.assertIn("Harbor Gate", status)
        self.assertIn("Asked Ren what it takes to reach the docks.", status)

    def test_build_turn_memory_entry_prefers_factual_summary(self) -> None:
        entry = build_turn_memory_entry(
            4,
            "I ask Ren about the docks",
            "Ren explained that only authorized workers may pass through the gate.",
            "",
        )
        self.assertEqual(
            entry,
            "Turn 4: Ren explained that only authorized workers may pass through the gate.",
        )

    def test_diff_runtime_state_reports_location_and_memory_changes(self) -> None:
        before = {
            "player_location": "Town Square",
            "discovered_keys": ["Town Square"],
            "quest_flags": {},
            "npc_locations": {"Ren": "Harbor Gate"},
            "story_status": "Before",
            "session_summary": ["Turn 1: Before"],
            "entities": {
                "Player": {
                    "entity_type": "player",
                    "location": "Town Square",
                    "inventory": [],
                    "memory": [],
                },
                "Ren": {
                    "entity_type": "npc",
                    "location": "Harbor Gate",
                    "inventory": [],
                    "memory": [],
                },
            },
            "items": {},
        }
        after = {
            "player_location": "Harbor Gate",
            "discovered_keys": ["Town Square", "Harbor Gate"],
            "quest_flags": {},
            "npc_locations": {"Ren": "Harbor Gate"},
            "story_status": "After",
            "session_summary": ["Turn 1: Before", "Turn 2: After"],
            "entities": {
                "Player": {
                    "entity_type": "player",
                    "location": "Harbor Gate",
                    "inventory": [],
                    "memory": ["Turn 2: Reached Harbor Gate."],
                },
                "Ren": {
                    "entity_type": "npc",
                    "location": "Harbor Gate",
                    "inventory": [],
                    "memory": [],
                },
            },
            "items": {},
        }

        delta = diff_runtime_state(before, after)

        self.assertEqual(delta["player_location"]["before"], "Town Square")
        self.assertEqual(delta["player_location"]["after"], "Harbor Gate")
        self.assertEqual(delta["discovered_keys"]["added"], ["Harbor Gate"])
        self.assertEqual(delta["entity_location_changes"][0]["entity"], "Player")
        self.assertEqual(delta["memory_changes"][0]["entity"], "Player")


class PromptContextTests(unittest.TestCase):
    def test_agent_prompt_contains_story_status_and_entity_block(self) -> None:
        state = PromptState(
            history_text="Player: I ask Ren about the docks.\nDM: Ren narrows his eyes.",
            beat_current="1/3: Investigate the town",
            beat_next="Follow the gate lead",
            beat_guide="Investigate, gate lead, confrontation",
            story_status="Current location: Harbor Gate. Latest resolved state: Ren blocked the passage.",
            session_summary="Turn 1: Arrived at Harbor Gate.\nTurn 2: Ren blocked the passage.",
            player_input="I ask Ren what it takes to get through to the docks.",
            current_location="Harbor Gate",
            scene_description="A guarded checkpoint blocks the road to the docks.",
            connected_locations=["Town Square", "Docks"],
            scene_actors=["Ren"],
            scene_items=["Gate Ledger"],
            entity_info={
                "Player": {"node_type": "player", "location": "Harbor Gate"},
                "Ren": {"node_type": "npc", "location": "Harbor Gate", "flags": "suspicious=yes"},
            },
        )

        prompt = build_agent_prompt(state)

        self.assertIn("# Story Status", prompt)
        self.assertIn("# Relevant World State", prompt)
        self.assertIn("Ren:", prompt)
        self.assertIn("Turn 1: Arrived at Harbor Gate.", prompt)


if __name__ == "__main__":
    unittest.main()

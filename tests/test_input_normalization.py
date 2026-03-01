from __future__ import annotations

import unittest

from orchestrator.normalization.lexicon import LexiconRecord
from orchestrator.normalization.normalize_input import InputNormalizer
from orchestrator.story import StoryGraph


class InputNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.normalizer = InputNormalizer.for_story(StoryGraph())

    def test_walk_into_bar_maps_enter_and_copper_cup(self) -> None:
        result = self.normalizer.normalize("I walk into the bar")
        self.assertEqual(result["normalized_intent"]["action_id"], "ACT_ENTER")
        self.assertIn("LOC_COPPER_CUP", result["normalized_intent"]["target_ids"])
        self.assertEqual(result["normalized_text"], "I enter the Copper Cup")

    def test_go_in_and_step_inside_map_to_enter(self) -> None:
        for text in ("go in", "step inside"):
            result = self.normalizer.normalize(text)
            self.assertEqual(result["normalized_intent"]["action_id"], "ACT_ENTER")

    def test_entity_alias_tavern_maps_to_copper_cup(self) -> None:
        result = self.normalizer.normalize("I head to the tavern")
        self.assertIn("LOC_COPPER_CUP", result["normalized_intent"]["target_ids"])
        self.assertIn("Copper Cup", result["normalized_text"])

    def test_ambiguity_returns_candidates_without_replacement(self) -> None:
        normalizer = InputNormalizer.from_records(
            [
                LexiconRecord("action", "ACT_MOVE", "move", ["go"]),
                LexiconRecord("location", "LOC_HARBOR_GATE", "Harbor Gate", ["gate"]),
                LexiconRecord("location", "LOC_NORTH_GATE", "North Gate", ["gate"]),
            ]
        )
        result = normalizer.normalize("go to the gate")
        self.assertEqual(result["normalized_text"], "move to the gate")
        self.assertTrue(result["ambiguities"])
        candidates = {c["concept_id"] for c in result["ambiguities"][0]["candidates"]}
        self.assertEqual(candidates, {"LOC_HARBOR_GATE", "LOC_NORTH_GATE"})

    def test_longest_match_wins_over_overlap(self) -> None:
        normalizer = InputNormalizer.from_records(
            [
                LexiconRecord("action", "ACT_MOVE", "move", ["walk"]),
                LexiconRecord("action", "ACT_ENTER", "enter", ["walk into"]),
                LexiconRecord("location", "LOC_COPPER_CUP", "Copper Cup", ["bar"]),
            ]
        )
        result = normalizer.normalize("I walk into the bar")
        self.assertEqual(result["normalized_intent"]["action_id"], "ACT_ENTER")
        action_match = next(match for match in result["matches"] if match["concept_type"] == "action")
        self.assertEqual(action_match["span"]["text"].lower(), "walk into")

    def test_approach_does_not_map_to_attack(self) -> None:
        result = self.normalizer.normalize("I approach and speak to the bartender")
        self.assertNotIn("attack", result["normalized_text"].lower())
        self.assertIn("move", result["normalized_text"].lower())

    def test_noisy_span_does_not_force_combat_action(self) -> None:
        result = self.normalizer.normalize("I approach and then speak with Mara")
        lowered = result["normalized_text"].lower()
        self.assertNotIn("attack", lowered)
        self.assertIn("talk", lowered)

    def test_ask_about_does_not_map_to_take(self) -> None:
        result = self.normalizer.normalize("I ask about the town")
        self.assertNotIn("take", result["normalized_text"].lower())


if __name__ == "__main__":
    unittest.main()

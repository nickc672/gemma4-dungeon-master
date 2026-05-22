from __future__ import annotations

import unittest

from orchestrator.normalization.lexicon import LexiconRecord
from orchestrator.normalization.normalize_input import InputNormalizer


class InputNormalizationTests(unittest.TestCase):
    """
    Tests for the input normalization pipeline.
    All test cases use InputNormalizer.from_records() so there is no
    dependency on a loaded WorldModel or external data files.
    """

    # ------------------------------------------------------------------
    # Basic action + location mapping
    # ------------------------------------------------------------------

    def test_walk_into_maps_to_enter(self) -> None:
        normalizer = InputNormalizer.from_records([
            LexiconRecord("action", "ACT_ENTER", "enter", ["walk into", "go inside"]),
            LexiconRecord("location", "LOC_COPPER_CUP", "Copper Cup", ["bar", "tavern"]),
        ])
        result = normalizer.normalize("I walk into the bar")
        self.assertEqual(result["normalized_intent"]["action_id"], "ACT_ENTER")
        self.assertIn("LOC_COPPER_CUP", result["normalized_intent"]["target_ids"])
        self.assertIn("Copper Cup", result["normalized_text"])

    def test_go_in_and_step_inside_map_to_enter(self) -> None:
        normalizer = InputNormalizer.from_records([
            LexiconRecord("action", "ACT_ENTER", "enter", ["go in", "step inside", "walk into"]),
        ])
        for text in ("go in", "step inside"):
            result = normalizer.normalize(text)
            self.assertEqual(result["normalized_intent"]["action_id"], "ACT_ENTER")

    def test_tavern_alias_maps_to_copper_cup(self) -> None:
        normalizer = InputNormalizer.from_records([
            LexiconRecord("action", "ACT_MOVE", "move", ["head to", "go to"]),
            LexiconRecord("location", "LOC_COPPER_CUP", "Copper Cup", ["tavern", "bar"]),
        ])
        result = normalizer.normalize("I head to the tavern")
        self.assertIn("LOC_COPPER_CUP", result["normalized_intent"]["target_ids"])
        self.assertIn("Copper Cup", result["normalized_text"])

    # ------------------------------------------------------------------
    # Ambiguity
    # ------------------------------------------------------------------

    def test_ambiguity_returns_candidates_without_replacement(self) -> None:
        normalizer = InputNormalizer.from_records([
            LexiconRecord("action", "ACT_MOVE", "move", ["go"]),
            LexiconRecord("location", "LOC_HARBOR_GATE", "Harbor Gate", ["gate"]),
            LexiconRecord("location", "LOC_NORTH_GATE", "North Gate", ["gate"]),
        ])
        result = normalizer.normalize("go to the gate")
        self.assertEqual(result["normalized_text"], "move to the gate")
        self.assertTrue(result["ambiguities"])
        candidates = {c["concept_id"] for c in result["ambiguities"][0]["candidates"]}
        self.assertEqual(candidates, {"LOC_HARBOR_GATE", "LOC_NORTH_GATE"})

    # ------------------------------------------------------------------
    # Longest-match
    # ------------------------------------------------------------------

    def test_longest_match_wins_over_overlap(self) -> None:
        normalizer = InputNormalizer.from_records([
            LexiconRecord("action", "ACT_MOVE", "move", ["walk"]),
            LexiconRecord("action", "ACT_ENTER", "enter", ["walk into"]),
            LexiconRecord("location", "LOC_COPPER_CUP", "Copper Cup", ["bar"]),
        ])
        result = normalizer.normalize("I walk into the bar")
        self.assertEqual(result["normalized_intent"]["action_id"], "ACT_ENTER")
        action_match = next(m for m in result["matches"] if m["concept_type"] == "action")
        self.assertEqual(action_match["span"]["text"].lower(), "walk into")

    # ------------------------------------------------------------------
    # Edge cases — no unintended combat mapping
    # ------------------------------------------------------------------

    def test_approach_does_not_map_to_attack(self) -> None:
        normalizer = InputNormalizer.from_records([
            LexiconRecord("action", "ACT_MOVE", "move", ["approach", "go toward"]),
            LexiconRecord("action", "ACT_TALK", "talk", ["speak", "speak to"]),
            LexiconRecord("action", "ACT_ATTACK", "attack", ["attack", "strike", "hit"]),
        ])
        result = normalizer.normalize("I approach and speak to the bartender")
        self.assertNotIn("attack", result["normalized_text"].lower())
        self.assertIn("move", result["normalized_text"].lower())

    def test_noisy_span_does_not_force_combat_action(self) -> None:
        normalizer = InputNormalizer.from_records([
            LexiconRecord("action", "ACT_MOVE", "move", ["approach"]),
            LexiconRecord("action", "ACT_TALK", "talk", ["speak", "speak with"]),
            LexiconRecord("action", "ACT_ATTACK", "attack", ["attack", "strike"]),
            LexiconRecord("npc", "NPC_MARA", "Mara", ["mara"]),
        ])
        result = normalizer.normalize("I approach and then speak with Mara")
        lowered = result["normalized_text"].lower()
        self.assertNotIn("attack", lowered)
        self.assertIn("talk", lowered)

    def test_ask_about_does_not_map_to_take(self) -> None:
        normalizer = InputNormalizer.from_records([
            LexiconRecord("action", "ACT_TALK", "talk", ["ask", "ask about"]),
            LexiconRecord("action", "ACT_TAKE", "take", ["take", "grab", "pick up"]),
        ])
        result = normalizer.normalize("I ask about the town")
        self.assertNotIn("take", result["normalized_text"].lower())


if __name__ == "__main__":
    unittest.main()

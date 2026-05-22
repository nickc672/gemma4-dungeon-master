=====
TESTS
=====

WHAT THIS IS

This folder holds the unit tests for the live orchestrator code.
Running "pytest" from the project root runs everything in here.

These tests do NOT call a real AI.
They check things that can be tested in isolation: data classes, parsers, the input normalizer, the before-and-after diffing logic.

If you want to know how well the AI is actually playing the game, that is the job of the "benchmark/" folder, not this one.


====================
FILES IN THIS FOLDER
====================

- "test_turn_reconciliation.py"
    Tests: "TurnReconciliationTests" and "PromptContextTests" (unittest-style).
    Covers: "orchestrator.runtime_flow.reconciliation" plus "orchestrator.llm_interaction.prompt_builders.PromptState" and "build_agent_prompt".

- "test_world_state_entities.py"
    Tests: "WorldStateEntityTests" (unittest-style).
    Covers: "orchestrator.world_state.entity", "item", "location", and "world_model".
    Verifies construction, key normalization, default player stats.
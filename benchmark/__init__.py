"""
=================================
BENCHMARK
=================================

WHAT THIS IS

This folder is the grading system for the LLMs and the system in general.
It runs the AI through pre-set scenarios, scores how well it performed, and produces a report.

Think of it as a standardized test for the AI Dungeon Master.
Each "test question" is a scenario - a set up of "the player is here, the world looks like this, and they just typed this".
The harness then asks the AI to handle one phase of that scenario, records what tools the AI called, compares the result against an answer key, and gives it a score.

The output is one JSON file per AI model.
You can then run a separate command that turns those JSON files into a single HTML page with tabs per model, a leaderboard, and detailed case-by-case results.


=============
HOW TO RUN IT
=============

Run all phases against one model and get both JSON + HTML:
    python3 -m benchmark.runner --model <model-name>


Run and skip the HTML (JSON only)
    python3 -m benchmark.runner --model <model-name> --no-html


Run specific tests only
    python3 -m benchmark.runner --model <model-name> --tests <phase_one|narration|phase_two>
                                                            (any combination - ex: phase_one, phase_two)


==========================
GENERATE COMPARISON REPORT
==========================
The runner writes one JSON file per model.
The report tool takes those files as input and produces a single HTML page.


Create Comparison Report, Auto-pick the N most recent results in the output directory
    python3 -m benchmark.report --latest 3


Latest with custom output path:
    python3 -m benchmark.report --latest 3 --output my_comparison.html


Select Specific files into an HTML report:
    python3 -m benchmark.report output/20260517_143000_llama3.1_8b_results.json


===================
FILES IN THIS FOLDER
===================

- "runner.py"
    The benchmark loop itself.
    For each scenario:
      1. builds a fresh "StoryEngine"
      2. configures its "GameState" to match the scenario
      3. calls just one phase ("engine.phase_one", "engine.narration", or "engine.phase_two") with the right input dataclass
      4. times it, scores the result, and writes the output to a per-model JSON file.

- "metrics.py"
    The scorer.
    Defines "Timer", "score_phase_one", "score_narration", "score_phase_two", and "summarize_results".
    Produces two layers of true-positives, false-positives, and false-negatives per scored case:
        - "function_calls": expected vs actual tool invocations.
        - "state_changes" (Phase 2 only): expected vs actual world-state mutations, derived from before-and-after snapshots.

- "report.py"
    The HTML generator.
    Takes one or more per-model JSON files and produces a single HTML report with per-model tabs, a leaderboard, and case-by-case detail.
    Has zero "orchestrator/" imports - it is pure JSON-to-HTML.

- "scenarios/phase_one_scenarios.py"
    Defines "PhaseOneCase" and the list of Phase 1 cases ("PHASE_ONE_CASES").
    Each case carries the player's input, the expected game state, the expected tool calls, and the expected keyword groups for the output.

- "scenarios/narration_scenarios.py"
    Defines "NarrationCase" and "NARRATION_CASES".
    Narration-phase scoring cases.

- "scenarios/phase_two_scenarios.py"
    Defines "PhaseTwoCase" and "PHASE_TWO_CASES".
    Write-phase cases, including expected state mutations.


==========================
WHY THE SCORING WORKS THIS WAY
==========================

For tool calls, the scorer uses a "closed-world" rule.
This means: only the tools listed in "expected_tools_called" (plus the phase's implicit finalize tool) are supposed to be called.
Anything else counts as a false positive.

For Phase 2, state changes are scored separately from tool calls.
This matters because the AI can call "move_to_location" correctly but pass the wrong arguments and end up not actually changing anything.
The state-change layer catches that.
this is also a grade for the system to make sure the code is correctly updating the game.


==============================================
THE PUBLIC INTERFACE THE BENCHMARK DEPENDS ON
==============================================

These are the names the benchmark imports from the orchestrator.
If you reorganize the orchestrator, these are the names that must continue to exist:

- "orchestrator.runtime_flow.pipeline.StoryEngine"
- The "engine.phase_one", "engine.narration", "engine.phase_two" attributes on a StoryEngine instance.
- "orchestrator.runtime_flow.phases.PhaseOneInput", "NarrationInput", "PhaseTwoInput"
- "orchestrator.runtime_flow.turn_context.TurnContext"
- "orchestrator.runtime_flow.reconciliation.build_runtime_state_snapshot"
- "orchestrator.world_state.story.mark_location_visited"
- "orchestrator.world_state.tools.bind_turn_orchestration_ctx" and "clear_turn_orchestration_ctx"

The runner's own module-level docstring also documents this contract.
"""
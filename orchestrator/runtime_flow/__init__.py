"""
=================================
ORCHESTRATOR / RUNTIME_FLOW
=================================

WHAT THIS IS

This folder is the heart of the turn loop.
When a player types something, the code in here is what actually drives the game forward:
    1. it gathers the current state of the world
    2. talks to the AI three times (once per phase)
    3. figures out what changed & adds the turn to history.

Think of this folder as the "Dungeon Master's procedure".
A human DM has a mental checklist for each turn: figure out what the player is doing, decide what happens, narrate it, and remember it for next time.


WHAT THIS FOLDER OWNS

- The "StoryEngine" class, which other code creates and calls.
- The three phase runners (Intent, Narrate, Writes), which live in the "phases/" subfolder.
- The per-turn context, the history of past turns, the snapshot-and-diff logic, and the small parsing helpers that the phases share.


====================
FILES IN THIS FOLDER
====================

- "pipeline.py"
    Defines "StoryEngine", the class everything else calls to advance one turn.
    Each turn, it builds the prompt state, takes a "before" snapshot of the world, runs the three phases in order, takes an "after" snapshot, commits the result to history.
    It also exposes "engine.phase_one", "engine.narration", and "engine.phase_two" as separate attributes so the benchmark harness can call any one phase by itself.

- "session_state.py"
    Defines "BeatTracker", "SessionSummary", and "SnapshotBuilder".
    "BeatTracker" knows which story beat the game is currently on.
    "SessionSummary" maintains a short, rolling text summary of what has happened so far (so the AI does not lose the thread over a long game).
    "SnapshotBuilder" writes session-checkpoint JSON files to disk so a session can be reloaded later.

- "conversation_log.py"
    Defines "History", a simple append-only list of past turns.
    Each turn it records the player's input, the narration that was produced, and the related metadata.
    Future prompts and the trace output read from this.

- "reconciliation.py"
    The "what changed this turn" logic.
    "build_runtime_state_snapshot" produces a comparable dictionary of the entire world at a given moment.
    "reconcile_turn" and "diff_runtime_state" compare a before and after snapshot, producing the change list that the trace and the benchmark scorer both consume.

- "state_builder.py"
    Defines "PromptStateBuilder" and "build_trace_state_snapshot".
    These take the engine's internal runtime objects and translate them into the "PromptState" dataclass that the prompt-builder code expects.
    Basically: "translate from runtime data into prompt-ready data".

- "step.py"
    Defines "LLMStep", a generic wrapper for the pattern "send one prompt, parse the labeled response, validate it".
    The narrate and intro phases use this directly.
    Also exports helpers like "parse_narrative" and "validate_narration_step".

- "step_registry.py"
    Defines "build_steps()", which returns the two "LLMStep" instances ("narrate", "intro") wired up with their system prompts.
    This is the catalog of standalone prompt steps that the engine can run.

- "turn_context.py"
    Defines "TurnContext", a dataclass that carries per-turn scratch data (the to-do list the AI built, side notes, transient flags) into the tool handlers.
    This is kept separate from the world model because it is different from the world state.
    The world state is facts that are true about the game world. Who is where. What items exist. What each character remembers. These persist across turns, they are the save file.
    The "TurnContext" is like the AI's notepad, temporary notes the AI took while figuring out this turn. These should not become part of the save file.

- "turn_heuristics.py"
    A small toolkit of regex parsers and string checks.
    Helpers include "_extract_labeled_line", "_extract_labeled_block", "_tool_call_succeeded", "_is_movement_request", "_is_trivial_player_input",
    and the regex pattern that matches Phase 2 tool names.
    The phase runners and the metrics scorer both use these to pull structured information out of the AI's labeled output.


===================
WHO IMPORTS THIS
===================

- "cli.py" imports "StoryEngine" and "write_session_checkpoint".
- "streamlit_app.py" imports "StoryEngine" and "BeatTracker".
- "benchmark/runner.py" imports "StoryEngine", "TurnContext", "build_runtime_state_snapshot", and the phase input dataclasses from "phases/".
- "benchmark/metrics.py" imports "_extract_labeled_line", "_extract_labeled_block", "_tool_call_succeeded", and "diff_runtime_state".


==================
SUBFOLDER: PHASES
==================

The "phases/" subfolder holds the three phase runners (Phase 1, Narration, Phase 2) plus the shared validators that decide when a phase has finished cleanly.
"""
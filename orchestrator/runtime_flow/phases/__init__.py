from .phase_one import Phase1Runner, PhaseOneInput, PhaseOneOutput
from .narration import NarrationRunner, NarrationInput, NarrationOutput
from .phase_two import Phase2Runner, PhaseTwoInput, PhaseTwoOutput

__all__ = [
    "Phase1Runner",
    "PhaseOneInput",
    "PhaseOneOutput",
    "NarrationRunner",
    "NarrationInput",
    "NarrationOutput",
    "Phase2Runner",
    "PhaseTwoInput",
    "PhaseTwoOutput",
]

"""
========================================
ORCHESTRATOR / RUNTIME_FLOW / PHASES
========================================

WHAT THIS IS

This folder contains the three "phase runners" that make up each turn.

1. Phase 1 - figure out what the player is trying to do & if they can do it.
2. Narration - write the text the player sees on screen.
3. Phase 2 - actually change the world to reflect what happened.

Each of those three jobs lives in its own file here.


HOW THESE CONNECT TO THE REST OF THE CODE

The main engine ("pipeline.StoryEngine") creates one instance of each runner when it starts up.
It then stores them as "engine.phase_one", "engine.narration", and "engine.phase_two".
The benchmark harness ("benchmark/runner.py") uses those same three public attributes to run one phase at a time against test scenarios.

If you ever rearrange how the runners are built, those three attribute names need to keep working.


===================
FILES IN THIS FOLDER
===================

- "phase_one.py"
    Defines "Phase1Runner" and its typed input and output dataclasses ("PhaseOneInput", "PhaseOneOutput").
    This runs the read-only Intent phase.
    During this phase, the AI is allowed to call any of these tools (all of which only read, never write):
        - "check_can_interact"
        - "get_current_context"
        - "list_scene_entities"
        - "get_entity_state"
        - "retrieve_memory_tool"
        - "skill_check"
        - "roll_dice"
        - "get_recent_skill_checks"
        - the various world-model getters.
    The phase ends only when the AI calls "finalize_turn".

- "phase_two.py"
    Defines "Phase2Runner" and its typed dataclasses.
    This runs the Writes phase, where the AI is allowed to actually change the world.
    It is restricted to the tools listed in "PHASE_2_TOOL_NAMES" (movement, memory writes, item moves, NPC creation, item creation).
    The phase ends when the AI calls "finalize_writes".
    It uses a regex pattern from "turn_heuristics.py" to catch the common bug where the AI mentions a change in prose but forgets to actually call the tool.

- "narration.py"
    Defines "NarrationRunner" and its typed dataclasses.
    This is a single-shot prompt: send it to the AI, get the prose back, done.
    The world has not been changed yet at this point, so the narration is grounded in the same world state the player has been looking at.
    No tool calls are allowed during this phase.


===================================
HOW PIPELINE WIRES THESE TOGETHER
===================================

"pipeline.py" imports the three runners and their input dataclasses like this:

    from .phases import (
        Phase1Runner, PhaseOneInput,
        NarrationRunner, NarrationInput,
        Phase2Runner, PhaseTwoInput,
    )

Each runner is constructed with:
- An "LLMAdapter" (from the "llm_interaction/" folder), which knows how to talk to the model.
- A prompt builder (from "llm_interaction/prompt_builders.py"), which knows how to assemble the prompt for that phase.
- The relevant tool definitions (from "world_state/tool_registry.py").
"""
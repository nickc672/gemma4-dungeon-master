"""Interactive story orchestration utilities."""

from .runtime_flow.pipeline import StoryEngine

__all__ = ["StoryEngine"]


"""
LLM_INTERACTION/ADAPTER.PY
Purpose: Central gateway to the LLM.
Classes:
    LLMAdapter
        Handles sending requests, retries, temperature control, parsing raw content.
    LLMError
        Raised when a stage fails after retries.


LLM_INTERACTION/PROMPT_BUILDERS.PY
Purpose: Build prompt text from structured state.
Classes:
    PromptState (dataclass)
        Snapshot of story/game state passed to all prompt builders.

        
RUNTIME_FLOW/STEP.PY
Purpose: Define and execute one LLM step.
Classes:
    LLMStep
        Represents a single LLM operation (intent, plan, validate, narrate, etc.)
Functions in this file:
    parse_sections
    parse_intent
    parse_focus
    parse_status
    parse_narrative
    Validators


RUNTIME_FLOW/STEP_REGISTRY.PY
Purpose: Register all steps in the pipeline.
Defines:
    build_steps()
        returns dictionary of LLMStep objects.

        
RUNTIME_FLOW/CONVERSATION_LOG.PY
Purpose: Store recent dialogue.
Classes:
    History
        Rolling window of player + narrator turns.


RUNTIME_FLOW/PIPELINE.PY
Purpose: Orchestrate a full game turn.
Classes:
    StoryEngine
        High-level controller that:  
            Builds PromptState
            Executes steps
            Updates world state
            Returns narration


RUNTIME_FLOW/SESSION_STATE.PY
Purpose: Manage non-LLM game state.
Classes:
    BeatTracker
    SessionSummary
    ActiveKeyManager
    FocusManager
    SnapshotBuilder


WORLD_STATE/WORLD_MODEL.PY
Purpose: Authored world model and story state.

Classes:
    WorldModel
JSON loading helpers


CLI.PY
Purpose: Command-line interface.
Contains:
    Argument parsing
    print_llm_verbose
    main()

"""

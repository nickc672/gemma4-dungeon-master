"""
========================================
ORCHESTRATOR / LLM_INTERACTION - OVERVIEW
========================================

WHAT THIS IS

This folder is the part of the code that actually talks to the AI model.
The rest of the system does not know or care which model is being used.
It just hands a request to this layer and gets a response back.

Think of this folder as a translator writing a letter to the model.
The translator takes the game's data (current location, what the player
just said, recent history) and writes it out as a prompt the model can
understand. Then it hands the prompt to your local Ollama runtime
and waits for an answer to return. The model on the other end can be
any tag the Ollama daemon has loaded - what changes between runs is
only the model tag in app_config.json.

Two main entry points are visible to the rest of the code:
- `LLMAdapter` (the class that sends a request and waits for a reply)
- The prompt-builder helpers (the functions that assemble the actual text of the prompt)

Everything else in this folder is internal.


WHY THIS IS SEPARATE FROM RUNTIME_FLOW

`runtime_flow/` knows about the game.
It knows the turn has three phases, it knows what a "world snapshot" is,
and it knows when to commit a turn to history.

`llm_interaction/` knows nothing about the game.
It only knows how to write a good prompt and how to make an API call.

Keeping these jobs apart means we can change how prompts are worded
without touching the turn loop, and change the turn loop without
worrying about transport details.


===================
FILES IN THIS LAYER
===================

- `adapter.py`
    Defines `LLMAdapter`, the class every phase of the turn loop uses to talk to the model.
    It is a thin wrapper over two things:
        1. An `OllamaClient` (which knows how to actually make the request).
        2. An `AgentLoop` (which handles the back-and-forth when the model wants to call tools).
    When created, it figures out which model to use from its constructor arguments,
    falling back to whatever `app_config.json` says.
    Also re-exports `LLMError` (the exception type for anything that goes wrong while
    talking to the model), and re-exports `DMC_ROLL_REQUIRED_SENTINEL` (a special marker
    the engine uses when a dice roll needs to be requested from the player).

- `agent_loop.py`
    Defines `AgentLoop`, `AgentHooks`, and `AgentResult`.
    This is the conversation loop that runs when the model decides to use a tool:
        1. send the prompt,
        2. get a response,
        3. run any tool calls the model made,
        4. send the tool results back,
        5. and keep going until the model is done or something tells it to stop.

- `ollama.py`
    The entire LLM-transport layer in one file.
    Defines the shared types (`LLMResponse`, `ToolCall`),
    the concrete `OllamaClient` class that talks to a local Ollama daemon,
    and the `get_shared_instance()` per-process singleton accessor.
    Anything Ollama-specific (message format translation, response parsing) lives
    here and nowhere else.

- `prompt_builders.py`
    Defines `PromptState` (a dataclass holding everything the model needs to know
    for one prompt) and four builder functions:
        1. `build_agent_prompt` (phase 1)
        2. `build_intro_prompt`
        3. `build_narrate_prompt`
        4. `build_phase_two_prompt`
    Each function turns the same `PromptState` into a slightly different prompt
    depending on which phase of the turn is running.
    The `PromptState` itself is constructed elsewhere, in `runtime_flow/state_builder.py`.

- `prompt_texts.py`
    The library of static prompt text.
    Holds the big system prompts (`PHASE_1_SYSTEM_PROMPT`, `PHASE_2_SYSTEM_PROMPT`,
    `NARRATE_PROMPT`, `INTRO_PROMPT`).
    Also holds all the smaller text fragments that `prompt_builders.py` puts together.
    No logic lives here, only strings.


===================
WHO USES THIS LAYER
===================

- `runtime_flow/pipeline.py` uses `LLMAdapter` (indirectly, through `runtime_flow/step.py`)
  and all four prompt builders.
- `runtime_flow/step.py` uses `LLMAdapter` and `LLMError`.
- `runtime_flow/step_registry.py` uses `NARRATE_PROMPT` and `INTRO_PROMPT` from `prompt_texts.py`.
- `benchmark/runner.py` uses this layer indirectly, through `StoryEngine`.


==========================================
WHY THERE IS AN ADAPTER AND AN AGENT_LOOP
==========================================

The older version of the code had a single big `LLMAdapter` class that did everything.
It knew the Ollama API, and it also ran the back-and-forth conversation when the
model used tools.
That mixed two unrelated jobs into one file.

The current version splits those jobs:
- `AgentLoop` (in `agent_loop.py`) handles the conversation back-and-forth.
- `OllamaClient` (in `ollama.py`) handles the Ollama API.
- `LLMAdapter` (in `adapter.py`) combines the two, so the rest of the codebase
  did not have to be rewritten when the split happened.

`pipeline.py`, `runner.py`, and `step.py` all rely on `LLMAdapter` being there.
"""
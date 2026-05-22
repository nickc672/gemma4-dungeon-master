"""
========================================
ORCHESTRATOR / LLM_INTERACTION - OVERVIEW
========================================

WHAT THIS IS

This folder is the part of the code that actually talks to the AI model.
The rest of the system does not know or care which AI is being used.
It just hands a request to this layer and gets a response back.

Think of this folder as a translator writing a letter to the LLM.
The translator takes the game's data (current location, what the player just said, recent history) and writes it out as a prompt the AI can understand.
Then it gives the prompt to whichever AI provider is configured (Ollama, OpenAI, or Anthropic), and waits for an answer to return.

Two main entry points are visible to the rest of the code:
- `LLMAdapter` (the class that sends a request and waits for a reply)
- The prompt-builder helpers (the functions that assemble the actual text of the prompt)

Everything else in this folder is internal.


WHY THIS IS SEPARATE FROM RUNTIME_FLOW

`runtime_flow/` knows about the game.
It knows the turn has three phases, it knows what a "world snapshot" is, and it knows when to commit a turn to history.

`llm_interaction/` knows nothing about the game.
It only knows how to write a good prompt and how to make an API call.

Keeping these jobs apart means we can swap out the AI provider, or change how prompts are worded, without touching the turn loop.
We can change the turn loop without worrying about API details.


===================
FILES IN THIS LAYER
===================

- `adapter.py`
    Defines `LLMAdapter`, the class every phase of the turn loop uses to talk to the AI.
    It is a thin wrapper over two things: 
        1. An `LLMProvider` (which knows how to actually call OpenAI / Anthropic / Ollama).
        2. An `AgentLoop` (which handles the back-and-forth when the AI wants to call tools).
    When created, it figures out which provider and model to use from its constructor arguments, falling back to whatever `app_config.json` says.
    Also re-exports `LLMError` (the exception type for anything that goes wrong while talking to the AI),
    and re-exports `DMC_ROLL_REQUIRED_SENTINEL` (a special marker the engine uses when a dice roll needs to be requested from the player).

- `agent_loop.py`
    Defines `AgentLoop`, `AgentHooks`, and `AgentResult`.
    This is the conversation loop that runs when the AI decides to use a tool: 
        1. send the prompt, 
        2. get a response, 
        3. run any tool calls the AI made, 
        4. send the tool results back, 
        5. and keep going until the AI is done or something tells it to stop.
    It does not know which AI provider is on the other end - that is the adapter's job.

- `prompt_builders.py`
    Defines `PromptState` (a dataclass holding everything the AI needs to know for one prompt) and four builder functions: 
        1. `build_agent_prompt` (phase 1)
        2. `build_intro_prompt`
        3. `build_narrate_prompt` 
        4. `build_phase_two_prompt`
    Each function turns the same `PromptState` into a slightly different prompt depending on which phase of the turn is running.
    The `PromptState` itself is constructed elsewhere, in `runtime_flow/state_builder.py`.

- `prompt_texts.py`
    The library of static prompt text.
    Holds the big system prompts (`PHASE_1_SYSTEM_PROMPT`, `PHASE_2_SYSTEM_PROMPT`, `NARRATE_PROMPT`, `INTRO_PROMPT`).
    Also holds all the smaller text fragments that `prompt_builders.py` puts together.
    No logic lives here, only strings.


SUBFOLDER

- `providers/`
    The concrete classes that actually call each AI service: `OllamaProvider`, `OpenAIProvider`, and `AnthropicProvider`.
    They all follow the same interface (`LLMProvider`), so the rest of this layer can use any of them interchangeably.
    See that folder's own _init_.py for details.


===================
WHO USES THIS LAYER
===================

- `runtime_flow/pipeline.py` uses `LLMAdapter` (indirectly, through `runtime_flow/step.py`) and all four prompt builders.
- `runtime_flow/step.py` uses `LLMAdapter` and `LLMError`.
- `runtime_flow/step_registry.py` uses `NARRATE_PROMPT` and `INTRO_PROMPT` from `prompt_texts.py`.
- `benchmark/runner.py` uses this layer indirectly, through `StoryEngine`.


==========================================
WHY THERE IS AN ADAPTER AND AN AGENT_LOOP
==========================================

The older version of the code had a single big `LLMAdapter` class that did everything.
The older version knew the API of each provider, and it ran the back-and-forth conversation when the AI used tools.
That mixed two unrelated jobs into one file.

The current version splits those jobs:
- `AgentLoop` (in `agent_loop.py`) handles the conversation back-and-forth.
- Each `LLMProvider` (in `providers/`) handles one specific API.
- `LLMAdapter` (in `adapter.py`) helped combined the two, so the rest of the codebase didn't have to be rewritten when the split happened.

`pipeline.py`, `runner.py`, and `step.py` all rely on `LLMAdapter` being there.
"""
from .runtime_flow.pipeline import StoryEngine
__all__ = ["StoryEngine"]


"""
=======================
ORCHESTRATOR - OVERVIEW
=======================

WHAT THIS IS

The orchestrator is the AI Dungeon Master that runs the game.
It plays single-player, text-only D&D-style adventures.
When a player types something into the CLI demo or the Streamlit web UI, every response, dice roll, and change to the world goes through this folder.


WHY IT'S BUILT THIS WAY

A human Dungeon Master mentally separates jobs across a turn: first they figure out what the player is trying to do, then they decide what happens, then they describe it out loud.
The orchestrator does the same thing on purpose, by splitting each turn into three steps:

1. INTENT
   The AI reads the world (current location, who is nearby, the story's outline), but isn't allowed to change anything yet.
   It uses this to work out what the player actually meant and intends to do.
   It also decides if the player is allowed to go though with their intended actions.
   For example, the LLMs commonly call "check_can_interact" on any entity to see if the player is allowed to interact with the character/object/location.
   The step ends when the AI calls "finalize_turn" with a short to-do list.

2. NARRATE
   The AI writes the text the player sees on screen.
   The world has not been changed yet, so the description helps guide the world updates.

3. WRITES
   Now the AI is allowed to actually change things (move the player or NPC, add a memory to a character, create a new item the narration just introduced).
   For example, the LLMs commonly call "write_memory" for the player, and for any NPC/location the player interacted with.
   The step ends when the AI calls "finalize_writes".

The same code runs whether you point it at Ollama, OpenAI, or Anthropic.
Which one is chosen is decided once at startup from "app_config.json", nothing inside the turn loop knows or cares.


===========================
WHAT LIVES IN ORCHESTRATOR
===========================

Files at the top of this folder:

- "cli.py"
    Displayes text and accepts test from the terminal.
    Run "python -m orchestrator.cli" to start playing.

- "app_config.py"
    Reads "app_config.json" and validates it.
    Anything that needs to know which AI provider, which model, or whether dice are manual or automatic asks this file.

- "app_config.json"
    The actual settings.
    Default is Ollama running locally with the "gpt-oss:20b" model.


Subfolders:

- "runtime_flow/"
    The turn loop itself.
    The "StoryEngine" class, the three phases, the history of past turns, and the before/after comparison logic.

- "llm_interaction/"
    Talking to the AI.
    Hides which provider is being used, assembles prompts, and handles the back-and-forth when the AI calls a tool.

- "world_state/"
    The game world.
    Characters, items, locations, the player, and all the tools the AI is allowed to call to read or change them.


==================================
HOW A TURN MOVES THROUGH THE CODE
==================================

When the player types something and the engine starts processing it ("pipeline.StoryEngine.advance_turn"):

1. "runtime_flow/state_builder.py" builds a "PromptState".
   This is a clean summary of the current world that can be dropped into a prompt.

2. "runtime_flow/reconciliation.py" takes a "world_before" snapshot.
   This is what the engine will compare against at the end of the turn to figure out what changed.

3. A new "TurnContext" (defined in "runtime_flow/turn_context.py") is bound to the game state.
   This is like the notepad the AI's tool calls write to during this turn - the to-do list, notes, flags.

4. "runtime_flow/phases/phase_one.py" runs the Intent phase.
   The AI can call any tool listed in "PHASE_1_TOOL_NAMES" (defined in "world_state/tool_registry.py"), all of them are read-only.

5. "runtime_flow/phases/narration.py" runs the Narrate phase.
   One call to the AI, and the result is the text the player sees.

6. "runtime_flow/phases/phase_two.py" runs the Writes phase.
   The AI is now restricted to "PHASE_2_TOOL_NAMES" - the tools that actually change the world.

7. "runtime_flow/reconciliation.py" takes a "world_after" snapshot.
   It compares it against "world_before", and produces a list of what actually changed this turn.

8. "runtime_flow/conversation_log.py" commits the turn to History.
   This way, later turns can refer back to it.


An extra file to help:
- "runtime_flow/turn_heuristics.py" is a small toolkit of regex parsers.
  The prompts ask the model to label its output ("Thoughts:", "Narrative:", "Recap:") and this file pulls those labeled chunks back out as plain Python strings.


======================
THE CONFIGURATION FILE
======================

Everything user-facing about which AI to use lives in "app_config.json".

- "llm.default_provider"
    One of "ollama", "openai", or "anthropic".
    Picks which company's API to talk to (or, for ollama, your local machine).

- "llm.providers.<name>.default_model" and "model_choices"
    For each provider: which model to use by default, and the menu of models the UI dropdown should offer.

- "llm.providers.<name>.default_options" and "stage_options"
    Sampling settings (temperature, max_tokens, and so on).
    "stage_options" lets each of the three phases override the defaults.
    For example, Narration uses a higher temperature so the prose feels less robotic. Phase 1 and Phase 2 stay low-temperature so they make consistent, predictable decisions.

- "rolls.mode"
    Either "auto" (the engine rolls a d20 itself) or "manual" (the CLI or web UI asks the human at the keyboard to roll a real die and type the result).

All three entry points read this file through "app_config.py": "cli.py", "streamlit_app.py", and "pipeline.py".
No code reads the JSON directly.
"""
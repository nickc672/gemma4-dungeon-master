from .runtime_flow.pipeline import StoryEngine
__all__ = ["StoryEngine"]


"""
=======================
ORCHESTRATOR - OVERVIEW
=======================

WHAT THIS IS

The orchestrator is the AI Dungeon Master that runs the game.
It plays single-player, text-only D&D-style adventures.
When a player types something into the CLI demo or the Streamlit web UI,
every response, dice roll, and change to the world goes through this folder.

Every model call lands on your local machine through Ollama, with no remote
API in the loop. The same orchestrator works with any Ollama-served model
the host has installed (Gemma, Llama, Mistral, Phi, and so on); the
system simply asks Ollama for whichever tag is currently configured.


WHY IT'S BUILT THIS WAY

A human Dungeon Master mentally separates jobs across a turn: first they
figure out what the player is trying to do, then they decide what
happens, then they describe it out loud.
The orchestrator does the same thing on purpose, by splitting each turn
into three steps:

1. INTENT
   The model reads the world (current location, who is nearby, the story's outline),
   but isn't allowed to change anything yet.
   It uses this to work out what the player actually meant and intends to do.
   It also decides if the player is allowed to go through with their intended actions.
   For example, the model commonly calls "check_can_interact" on any entity to see
   if the player is allowed to interact with the character/object/location.
   The step ends when the model calls "finalize_turn" with a short to-do list.

2. NARRATE
   The model writes the text the player sees on screen.
   The world has not been changed yet, so the description helps guide the world updates.

3. WRITES
   Now the model is allowed to actually change things (move the player or NPC,
   add a memory to a character, create a new item the narration just introduced).
   For example, the model commonly calls "write_memory" for the player, and for
   any NPC/location the player interacted with.
   The step ends when the model calls "finalize_writes".

The same model handles all three phases. Per-phase sampling options
("stage_options" in app_config.json) keep Phase 1 and Phase 2
low-temperature so tool calls stay disciplined, while bumping
Narration's temperature so the prose has some life in it.


===========================
WHAT LIVES IN ORCHESTRATOR
===========================

Files at the top of this folder:

- "cli.py"
    Displays text and accepts text from the terminal.
    Run "python -m orchestrator.cli" to start playing.

- "app_config.py"
    Reads "app_config.json" and validates it.
    Anything that needs to know which model to use, or whether dice
    are manual or automatic, asks this file.

- "app_config.json"
    The actual settings.
    Holds the default model, the menu of model choices the UI shows,
    the sampling options applied to each phase, and the roll mode.


Subfolders:

- "runtime_flow/"
    The turn loop itself.
    The "StoryEngine" class, the three phases, the history of past turns,
    and the before/after comparison logic.

- "llm_interaction/"
    Talking to the model.
    Builds prompts and runs the back-and-forth when the model calls a tool.

- "world_state/"
    The game world.
    Characters, items, locations, the player, and all the tools the model
    is allowed to call to read or change them.


==================================
HOW A TURN MOVES THROUGH THE CODE
==================================

When the player types something and the engine starts processing it
("pipeline.StoryEngine.run_turn"):

1. "runtime_flow/state_builder.py" builds a "PromptState".
   This is a clean summary of the current world that can be dropped into a prompt.

2. "runtime_flow/reconciliation.py" takes a "world_before" snapshot.
   This is what the engine will compare against at the end of the turn to figure out what changed.

3. A new "TurnContext" (defined in "runtime_flow/turn_context.py") is bound to the game state.
   This is like the notepad the model's tool calls write to during this turn -
   the to-do list, notes, flags.

4. "runtime_flow/phases/phase_one.py" runs the Intent phase.
   The model can call any tool listed in "PHASE_1_TOOL_NAMES" (defined in
   "world_state/tool_registry.py"), all of them are read-only.

5. "runtime_flow/phases/narration.py" runs the Narrate phase.
   One call to the model, and the result is the text the player sees.

6. "runtime_flow/phases/phase_two.py" runs the Writes phase.
   The model is now restricted to "PHASE_2_TOOL_NAMES" - the tools that actually
   change the world.

7. "runtime_flow/reconciliation.py" takes a "world_after" snapshot.
   It compares it against "world_before", and produces a list of what actually
   changed this turn.

8. "runtime_flow/conversation_log.py" commits the turn to History.
   This way, later turns can refer back to it.


An extra file to help:
- "runtime_flow/turn_heuristics.py" is a small toolkit of regex parsers.
  The prompts ask the model to label its output ("Thoughts:", "Narrative:",
  "Recap:") and this file pulls those labeled chunks back out as plain Python
  strings.


======================
THE CONFIGURATION FILE
======================

Everything user-facing about the model lives in "app_config.json".

- "model.default"
    The Ollama tag the engine uses by default if no override is passed
    on the CLI or in the Streamlit sidebar.

- "model.choices"
    The menu of model tags the UI dropdown should offer. The Streamlit
    sidebar also appends anything else the local Ollama daemon reports
    installed, so the dropdown grows automatically as the user pulls
    new models.

- "model.default_options" and "model.stage_options"
    Sampling settings (temperature, top_p, num_ctx, and so on).
    "stage_options" lets each of the three phases override the defaults.
    Narration uses a higher temperature so the prose feels less robotic.
    Phase 1 and Phase 2 stay low-temperature so they make consistent,
    predictable tool calls.

- "rolls.mode"
    Either "auto" (the engine rolls a d20 itself) or "manual" (the CLI or
    web UI asks the human at the keyboard to roll a real die and type the
    result).

All three entry points read this file through "app_config.py":
"cli.py", "streamlit_app.py", and "pipeline.py".
No code reads the JSON directly.
"""
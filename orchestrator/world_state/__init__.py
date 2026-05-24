"""
==========================
ORCHESTRATOR / WORLD_STATE
==========================

WHAT THIS IS

This folder owns the game world.
Everything the AI knows about the player, the characters, the items, and the locations comes from this folder.
Every tool the AI is allowed to use to look at the world, or change it, is defined here.
The folder loads its world data from JSON files in "orchestrator/data/world_model/".


==========
DATA MODEL
==========

These files define the shape of the things in the world.
They are dataclasses with very little logic.

- "entity.py"
    Defines "BaseEntity" (the parent of everything in the world), "Entity" (NPCs), "Player" (the player character), and "DynamicSentenceMemory" (the per-entity memory store).
    Also defines "MemoryHit", which represents one result from a memory lookup.
    Also holds the default player stats and skills.
    Note: "DynamicSentenceMemory" is currently a "lexical search only" placeholder.
    The FAISS-based version that was prototyped in the notebooks was not adopted.

- "item.py"
    Defines "Item".
    A simple dataclass holding an item's key, name, description, who is holding it, and whether it is portable.

- "location.py"
    Defines "Location".
    A simple dataclass holding a location's key, name, description, and which other locations it is connected to.

- "world_model.py"
    Defines "WorldModel" (the in-memory container for the whole world), "WORLD_MODEL_DATA_DIR" (where the JSON files live), and the loading helpers "build_world_model" and "resolve_world_model_data_dir".
    Loads "story.json", "locations.json", "actors.json", and "items.json" from the data directory.
    The per-story copy is found by "story_library".
    Can also serialize the world back to JSON for save-file checkpoints.

- "story.py"
    Defines "GameState", the per-session mutable state that sits on top of the immutable "WorldModel".
    Holds things like the player's current location, the visited-locations set, which beats have happened.
    Also includes helpers like "create_initial_game_state", "mark_location_visited", and "recompute_discovered_locations".

- "story_library.py"
    Defines "StorySource", "list_story_sources", and "get_story_source".
    Used only by the Streamlit UI to populate the "pick a story to play" dropdown.
    Lists playable stories from "orchestrator/data/stories/".
    If that folder is empty, it falls back to the default world-model data.


=====================
TOOLS THE AI CAN CALL
=====================

These files hold the actual tool implementations.
Each file is one "family" of related tools.
Each tool family exports both the function (which the runtime executes) and a "*_TOOL_DEFINITIONS" list (the JSON schema the AI sees).

- "entity_tools.py"
    Read an NPC's or player's state, look something up in their memory, write a new memory.
    Exports "ENTITY_TOOL_DEFINITIONS".

- "mechanics_tools.py"
    Dice rolls, skill checks, the history of recent skill checks.
    Exports "MECHANICS_TOOL_DEFINITIONS".

- "scene_tools.py"
    Tools related to the current location: look around, see who is here, move to a connected location, move an NPC, check whether the player can interact with something.
    Exports "SCENE_TOOL_DEFINITIONS" and "VALIDATE_TOOLS".

- "turn_tools.py"
    Per-turn bookkeeping tools: build or update the to-do list, add notes, and the two "finalize" tools ("finalize_turn", "finalize_writes") that signal the end of each phase.

- "world_model_tools.py"
    World-wide tools: read or list the entire world's story, locations, entities, items.
    Also includes the two "creation" tools ("create_npc", "create_item") that materialize new NPCs and items mid-game.
    Enforces per-turn caps on how many new things can be created (so the AI cannot spawn an army by accident).


==========
REGISTRIES
==========

These files connect everything together so the engine can find and call the right tool by name.

- "tool_runtime.py"
    Shared runtime state for tool handlers.
    Holds the alias registry (so "the bartender" can map to a specific NPC key), the dynamic memory cache, todo-status constants, the world-checkpoint root.
    Also holds helpers like "find_entity", "find_world_object", "entity_public_view", "skill_check_log", and the "bind_turn_orchestration_ctx" / "clear_turn_orchestration_ctx" pair used by the pipeline to scope each turn.

- "tool_registry.py"
    The master tool catalog.
    Defines which tool names are allowed in Phase 1 vs Phase 2 ("PHASE_1_TOOL_NAMES", "PHASE_2_TOOL_NAMES", "SPAWN_TOOL_NAMES").
    Defines the matching JSON-schema lists ("PHASE_1_TOOL_DEFINITIONS", "PHASE_2_TOOL_DEFINITIONS").
    Defines "RUNTIME_TOOL_HANDLERS", the dispatch table that maps each tool name to its actual function.
    Provides the "execute_tool" and "execute_world_model_tool" entrypoints that the phase runners call.

- "tools.py"
    A pure re-export aggregator.
    Lets "pipeline.py" and "benchmark/runner.py" pull every name they need from one place instead of chasing five submodules.


=======================
WHO IMPORTS THIS FOLDER
=======================

- "runtime_flow/pipeline.py" uses the "tools.py" aggregator and "world_model.py".
- "runtime_flow/state_builder.py" reads "GameState".
- "runtime_flow/reconciliation.py" uses "story.recompute_discovered_locations".
- "cli.py" uses "tool_runtime.set_world_checkpoint_root" and "world_model.build_world_model".
- "streamlit_app.py" uses "tool_runtime.set_world_checkpoint_root", "world_model.build_world_model", and "story_library.list_story_sources".
- "benchmark/runner.py" uses "story.mark_location_visited" and the "bind_turn_orchestration_ctx" / "clear_turn_orchestration_ctx" pair from "tools".
"""
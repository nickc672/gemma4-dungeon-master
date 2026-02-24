# orchestrator/world_state/tools.py
import json
import random
from typing import Any, Dict, List, Optional

from .entity import (
    DEFAULT_PLAYER_SKILLS,
    DEFAULT_PLAYER_STATS,
    DynamicSentenceMemory,
    Entity,
    split_into_sentences as _split_into_sentences,
)
from .story import GameState, StoryGraph, NodeType

SKILL_TO_STAT: Dict[str, str] = {
    "acrobatics": "dexterity",
    "animal_handling": "wisdom",
    "arcana": "intelligence",
    "athletics": "strength",
    "deception": "charisma",
    "history": "intelligence",
    "insight": "wisdom",
    "intimidation": "charisma",
    "investigation": "intelligence",
    "medicine": "wisdom",
    "nature": "intelligence",
    "perception": "wisdom",
    "performance": "charisma",
    "persuasion": "charisma",
    "religion": "intelligence",
    "sleight_of_hand": "dexterity",
    "stealth": "dexterity",
    "survival": "wisdom",
}

TODO_ACTIVE_STATUSES = {"pending", "in_progress"}
TODO_FINAL_STATUSES = {"done", "skipped", "blocked"}
TODO_ALLOWED_STATUSES = TODO_ACTIVE_STATUSES | TODO_FINAL_STATUSES

# Small curated memory seeds for demoability / early RAG behavior.
# These are added once when an entity is first materialized in the registry.
ENTITY_MEMORY_SEEDS: Dict[str, List[str]] = {
    "mitch": [
        "Mitch says he found one of the first bloodstains near the Riverside Path before dawn.",
        "Mitch keeps blaming the town wizard, but his story changes when pressed for exact times.",
        "Mitch looks exhausted and jittery, like he has not slept properly in several nights.",
        "Mitch's hands are heavily calloused from woodcutting, and he smells like sap, smoke, and wet earth.",
    ],
}

def _normalize_key(text: str) -> str:
    return str(text or "").strip().lower()


def _apply_turn_ctx_defaults(ctx: dict[str, Any]) -> dict[str, Any]:
    ctx.setdefault("phase", "")
    ctx.setdefault("todo", [])
    ctx.setdefault("todo_revision", 0)
    ctx.setdefault("todo_summary", "")
    ctx.setdefault("notes", [])
    ctx.setdefault("current_focus", [])
    ctx.setdefault("active_keys", [])
    return ctx


def _entity_registry(game_state: GameState) -> Dict[str, Entity]:
    registry = getattr(game_state, "entity_registry", None)
    if registry is None:
        registry = {}
        setattr(game_state, "entity_registry", registry)
    return registry


def _seed_entity_example_memories(entity: Entity) -> None:
    seed_key = _normalize_key(entity.key)
    seeds = ENTITY_MEMORY_SEEDS.get(seed_key, [])
    if not seeds:
        return

    metadata = entity.metadata if isinstance(entity.metadata, dict) else {}
    if metadata.get("_example_memory_seeded"):
        return

    entity.memory.add_sentences(list(seeds))
    metadata["_example_memory_seeded"] = True
    entity.metadata = metadata


def _skill_check_log(game_state: GameState) -> List[dict[str, Any]]:
    log = getattr(game_state, "skill_check_log", None)
    if log is None:
        log = []
        setattr(game_state, "skill_check_log", log)
    return log


def _node_location(node_key: str, node_type: NodeType, game_state: GameState, story_graph: StoryGraph) -> str:
    if node_type == NodeType.LOCATION:
        return node_key
    if node_type == NodeType.NPC:
        return game_state.npc_locations.get(node_key) or next(
            (c for c in story_graph.get_node(node_key).connections if story_graph.get_node(c) and story_graph.get_node(c).node_type == NodeType.LOCATION),
            (story_graph.get_node(node_key).connections[0] if story_graph.get_node(node_key) and story_graph.get_node(node_key).connections else "unknown"),
        )
    node = story_graph.get_node(node_key)
    if not node or not node.connections:
        return "unknown"
    for connection in node.connections:
        target = story_graph.get_node(connection)
        if target and target.node_type == NodeType.LOCATION:
            return connection
    return str(node.connections[0])


def _default_entity_skills(node_type: NodeType, key: str) -> Dict[str, int]:
    if key == "Player":
        return dict(DEFAULT_PLAYER_SKILLS)
    if node_type == NodeType.NPC:
        return {"insight": 1, "perception": 1, "persuasion": 0}
    if node_type == NodeType.CLUE:
        return {"investigation": 0}
    return {}


def _default_entity_stats(node_type: NodeType, key: str) -> Dict[str, int]:
    if key == "Player":
        return dict(DEFAULT_PLAYER_STATS)
    if node_type == NodeType.NPC:
        return {
            "strength": 10,
            "dexterity": 10,
            "constitution": 10,
            "intelligence": 10,
            "wisdom": 10,
            "charisma": 10,
        }
    return {}


def ensure_entity_registry(game_state: GameState, story_graph: StoryGraph) -> Dict[str, Entity]:
    registry = _entity_registry(game_state)

    # Player entity is useful for skill checks and shared mechanics tooling.
    player = registry.get("player")
    if player is None:
        player = Entity(
            key="Player",
            name="Player",
            entity_type="player",
            description="The player character controlled by the user.",
            location=game_state.player_location,
            skills=dict(DEFAULT_PLAYER_SKILLS),
            stats=dict(DEFAULT_PLAYER_STATS),
            tags=["player"],
        )
        player.memory.add_sentences(
            [
                "The player is investigating the harbor town mystery.",
                f"The player is currently at {game_state.player_location}.",
            ]
        )
        registry["player"] = player
    else:
        player.set_location(game_state.player_location)
        if "player" not in player.tags:
            player.tags.append("player")

    for node in story_graph.nodes:
        reg_key = _normalize_key(node.key)
        location = _node_location(node.key, node.node_type, game_state, story_graph)
        entity = registry.get(reg_key)

        if entity is None:
            entity = Entity(
                key=node.key,
                name=node.key,
                entity_type=node.node_type.value,
                description=node.description,
                location=location,
                skills=_default_entity_skills(node.node_type, node.key),
                stats=_default_entity_stats(node.node_type, node.key),
                tags=list(node.tags or ()),
                metadata={"connections": list(node.connections)},
            )
            entity.memory.add_sentences(
                [
                    *(_split_into_sentences(node.description) or [node.description]),
                    f"{node.key} is associated with {location}.",
                ]
            )
            _seed_entity_example_memories(entity)
            registry[reg_key] = entity
            continue

        entity.description = node.description
        entity.entity_type = node.node_type.value
        entity.set_location(location)
        entity.metadata["connections"] = list(node.connections)
        if not entity.skills:
            entity.skills = _default_entity_skills(node.node_type, node.key)
        if not entity.stats:
            entity.stats = _default_entity_stats(node.node_type, node.key)
        if not entity.tags:
            entity.tags = list(node.tags or ())
        _seed_entity_example_memories(entity)

    return registry


def _find_entity(entity_key: str, game_state: GameState, story_graph: StoryGraph) -> Optional[Entity]:
    registry = ensure_entity_registry(game_state, story_graph)
    return registry.get(_normalize_key(entity_key))


def _entity_public_view(entity: Entity, *, include_memory_preview: bool = False, memory_preview: int = 3) -> dict[str, Any]:
    return entity.to_public_view(
        include_memory_preview=include_memory_preview,
        memory_preview=memory_preview,
    )


def bind_turn_orchestration_ctx(game_state: GameState, ctx: dict[str, Any]) -> None:
    """Attach the current turn's orchestration context to game state for tool access."""
    if not isinstance(ctx, dict):
        raise ValueError("ctx must be a dict")
    setattr(game_state, "_turn_orchestration_ctx", _apply_turn_ctx_defaults(ctx))


def clear_turn_orchestration_ctx(game_state: GameState) -> None:
    """Detach any bound turn orchestration context."""
    if hasattr(game_state, "_turn_orchestration_ctx"):
        delattr(game_state, "_turn_orchestration_ctx")


def _require_turn_orchestration_ctx(game_state: GameState) -> dict[str, Any]:
    ctx = getattr(game_state, "_turn_orchestration_ctx", None)
    if not isinstance(ctx, dict):
        raise RuntimeError("No turn orchestration context is bound to game_state.")
    return _apply_turn_ctx_defaults(ctx)


def _compute_turn_todo_counts(ctx: dict[str, Any]) -> dict[str, int]:
    items = ctx.get("todo", [])
    counts = {
        "total": len(items),
        "pending": 0,
        "in_progress": 0,
        "done": 0,
        "skipped": 0,
        "blocked": 0,
    }
    for item in items:
        status = str(item.get("status", "pending")).strip().lower()
        if status in counts:
            counts[status] += 1
        else:
            counts["pending"] += 1
    return counts


def _find_turn_todo_item(ctx: dict[str, Any], item_id: int) -> Optional[dict[str, Any]]:
    for item in ctx.get("todo", []):
        if int(item.get("id", -1)) == int(item_id):
            return item
    return None


def _normalize_turn_todo_item(raw: Any, item_id: int) -> Dict[str, Any]:
    if isinstance(raw, str):
        task = raw.strip()
        raw_obj: Dict[str, Any] = {}
    elif isinstance(raw, dict):
        raw_obj = dict(raw)
        task = str(raw_obj.get("task") or raw_obj.get("description") or "").strip()
    else:
        raise ValueError(f"Invalid todo item {item_id}: expected string or object")

    if not task:
        raise ValueError(f"Todo item {item_id} must include a non-empty task")

    tool_name = str(raw_obj.get("tool_name", "")).strip()
    arguments_hint = raw_obj.get("arguments_hint") or {}
    if not isinstance(arguments_hint, dict):
        arguments_hint = {}

    requires_tool = bool(raw_obj.get("requires_tool", False))
    if tool_name and "requires_tool" not in raw_obj:
        requires_tool = True

    return {
        "id": int(item_id),
        "task": task,
        "requires_tool": requires_tool,
        "tool_name": tool_name,
        "arguments_hint": arguments_hint,
        "status": "pending",
        "resolution": "",
        "used_tool": False,
    }


def set_turn_todo(
    items: list[Any],
    plan_summary: str = "",
    game_state: GameState | None = None,
    story_graph: StoryGraph | None = None,
) -> dict[str, Any]:
    """Create or replace the current turn todo list."""
    _ = story_graph
    if game_state is None:
        raise RuntimeError("Missing game_state context.")

    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty list")

    ctx = _require_turn_orchestration_ctx(game_state)
    normalized = [_normalize_turn_todo_item(raw, idx) for idx, raw in enumerate(items, start=1)]
    ctx["todo"] = normalized
    ctx["todo_summary"] = str(plan_summary).strip()
    ctx["todo_revision"] = int(ctx.get("todo_revision", 0)) + 1

    return {
        "ok": True,
        "revision": ctx["todo_revision"],
        "summary": ctx["todo_summary"],
        "items": normalized,
        "counts": _compute_turn_todo_counts(ctx),
    }


def get_turn_todo(
    include_completed: bool = True,
    game_state: GameState | None = None,
    story_graph: StoryGraph | None = None,
) -> dict[str, Any]:
    """Read the current turn todo list."""
    _ = story_graph
    if game_state is None:
        raise RuntimeError("Missing game_state context.")
    ctx = _require_turn_orchestration_ctx(game_state)

    if include_completed:
        items = list(ctx["todo"])
    else:
        items = [
            item for item in ctx["todo"]
            if str(item.get("status", "pending")).strip().lower() in TODO_ACTIVE_STATUSES
        ]

    return {
        "ok": True,
        "revision": int(ctx.get("todo_revision", 0)),
        "summary": str(ctx.get("todo_summary", "")),
        "items": items,
        "counts": _compute_turn_todo_counts(ctx),
    }


def set_todo_item_status(
    item_id: int,
    status: str,
    resolution: str = "",
    used_tool: bool = False,
    game_state: GameState | None = None,
    story_graph: StoryGraph | None = None,
) -> dict[str, Any]:
    """Mark a todo item status and resolution."""
    _ = story_graph
    if game_state is None:
        raise RuntimeError("Missing game_state context.")
    ctx = _require_turn_orchestration_ctx(game_state)

    item = _find_turn_todo_item(ctx, int(item_id))
    if item is None:
        raise ValueError(f"Todo item {item_id} not found")

    normalized_status = str(status).strip().lower().replace(" ", "_").replace("-", "_")
    if normalized_status in {"complete", "completed", "finish", "finished"}:
        normalized_status = "done"
    elif normalized_status == "skip":
        normalized_status = "skipped"
    elif normalized_status == "inprogress":
        normalized_status = "in_progress"
    if normalized_status not in TODO_ALLOWED_STATUSES:
        raise ValueError(f"Invalid status '{status}'")

    resolution_text = str(resolution).strip()
    item["status"] = normalized_status
    item["resolution"] = resolution_text
    item["used_tool"] = bool(used_tool)

    return {
        "ok": True,
        "item": item,
        "counts": _compute_turn_todo_counts(ctx),
    }


def get_turn_progress(
    game_state: GameState | None = None,
    story_graph: StoryGraph | None = None,
) -> dict[str, Any]:
    """Read orchestration progress for the current turn."""
    _ = story_graph
    if game_state is None:
        raise RuntimeError("Missing game_state context.")
    ctx = _require_turn_orchestration_ctx(game_state)
    return {
        "ok": True,
        "phase": str(ctx.get("phase", "")),
        "todo_revision": int(ctx.get("todo_revision", 0)),
        "todo_counts": _compute_turn_todo_counts(ctx),
        "current_focus": list(ctx.get("current_focus", [])),
        "active_keys": list(ctx.get("active_keys", [])),
        "player_location": getattr(game_state, "player_location", ""),
    }


def add_turn_note(
    text: str,
    game_state: GameState | None = None,
    story_graph: StoryGraph | None = None,
) -> dict[str, Any]:
    """Add a note to the current turn orchestration context."""
    _ = story_graph
    if game_state is None:
        raise RuntimeError("Missing game_state context.")
    ctx = _require_turn_orchestration_ctx(game_state)

    note = str(text).strip()
    if not note:
        raise ValueError("text cannot be empty")
    notes = ctx.setdefault("notes", [])
    notes.append(note)
    return {"ok": True, "note": note, "total_notes": len(notes)}


def check_can_interact(entity_key: str, game_state: GameState, story_graph: StoryGraph) -> dict[str, Any]:
    """Check if player can interact with an entity."""
    node = story_graph.get_node(entity_key)
    
    if not node:
        return {
            "success": False,
            "can_interact": False,
            "reason": f"Entity '{entity_key}' does not exist."
        }
    
    player_loc = game_state.player_location
    
    if node.node_type == NodeType.LOCATION:
        current_node = story_graph.get_node(player_loc)
        if not current_node:
            return {"success": False, "can_interact": False, "reason": "Invalid player location"}
        
        if entity_key == player_loc:
            return {
                "success": True,
                "can_interact": True,
                "entity_type": "location",
                "reason": "You are already at this location."
            }
        
        if entity_key in current_node.connections:
            return {
                "success": True,
                "can_interact": True,
                "entity_type": "location",
                "reason": f"{entity_key} is accessible from here."
            }
        
        return {
            "success": True,
            "can_interact": False,
            "entity_type": "location",
            "reason": f"{entity_key} is not connected to {player_loc}."
        }
    
    elif node.node_type == NodeType.NPC:
        npc_location = game_state.npc_locations.get(entity_key)
        if npc_location is None:
            npc_location = node.connections[0] if node.connections else None
        
        if npc_location == player_loc:
            return {
                "success": True,
                "can_interact": True,
                "entity_type": "npc",
                "reason": f"{entity_key} is here."
            }
        
        return {
            "success": True,
            "can_interact": False,
            "entity_type": "npc",
            "reason": f"{entity_key} is at {npc_location}."
        }
    
    elif node.node_type in (NodeType.ITEM, NodeType.CLUE):
        entity_location = node.connections[0] if node.connections else None
        
        if entity_location == player_loc:
            return {
                "success": True,
                "can_interact": True,
                "entity_type": node.node_type.value,
                "reason": f"{entity_key} is here."
            }
        
        return {
            "success": True,
            "can_interact": False,
            "entity_type": node.node_type.value,
            "reason": f"{entity_key} is at {entity_location}."
        }
    
    return {"success": False, "can_interact": False, "reason": "Unknown entity type"}


def move_to_location(location_key: str, game_state: GameState, story_graph: StoryGraph) -> dict[str, Any]:
    """Move player to a new location."""
    node = story_graph.get_node(location_key)
    
    if not node:
        return {
            "success": False,
            "new_location": None,
            "reason": f"Location '{location_key}' does not exist."
        }
    
    if node.node_type != NodeType.LOCATION:
        return {
            "success": False,
            "new_location": None,
            "reason": f"'{location_key}' is not a location."
        }
    
    current_node = story_graph.get_node(game_state.player_location)
    if not current_node:
        return {"success": False, "new_location": None, "reason": "Invalid current location."}
    
    if location_key == game_state.player_location:
        return {
            "success": True,
            "new_location": location_key,
            "reason": "You are already here."
        }
    
    if location_key not in current_node.connections:
        return {
            "success": False,
            "new_location": None,
            "reason": f"Cannot move to {location_key}. Not connected to {game_state.player_location}."
        }
    
    # Move the player
    game_state.player_location = location_key
    game_state.discovered_keys.add(location_key)
    
    return {
        "success": True,
        "new_location": location_key,
        "reason": f"Moved to {location_key}."
    }


def get_current_context(game_state: GameState, story_graph: StoryGraph) -> dict[str, Any]:
    """Get information about player's current location."""
    current_node = story_graph.get_node(game_state.player_location)
    
    if not current_node:
        return {
            "location": game_state.player_location,
            "description": "Unknown location",
            "connected_locations": [],
            "npcs_here": [],
            "items_here": []
        }
    
    # Find NPCs at this location
    npcs_here = []
    for node in story_graph.nodes:
        if node.node_type == NodeType.NPC:
            npc_location = game_state.npc_locations.get(node.key)
            if npc_location is None:
                npc_location = node.connections[0] if node.connections else None
            if npc_location == game_state.player_location:
                npcs_here.append(node.key)
    
    # Find items/clues at this location
    items_here = []
    for node in story_graph.nodes:
        if node.node_type in (NodeType.ITEM, NodeType.CLUE):
            item_location = node.connections[0] if node.connections else None
            if item_location == game_state.player_location:
                items_here.append(node.key)
    
    return {
        "location": game_state.player_location,
        "description": current_node.description,
        "connected_locations": list(current_node.connections),
        "npcs_here": npcs_here,
        "items_here": items_here
    }


def move_npc(npc_key: str, new_location: str, game_state: GameState, story_graph: StoryGraph) -> dict[str, Any]:
    """Move an NPC to a new location (DM tool)."""
    npc_node = story_graph.get_node(npc_key)
    location_node = story_graph.get_node(new_location)
    
    if not npc_node:
        return {"success": False, "reason": f"NPC '{npc_key}' does not exist."}
    
    if npc_node.node_type != NodeType.NPC:
        return {"success": False, "reason": f"'{npc_key}' is not an NPC."}
    
    if not location_node:
        return {"success": False, "reason": f"Location '{new_location}' does not exist."}
    
    if location_node.node_type != NodeType.LOCATION:
        return {"success": False, "reason": f"'{new_location}' is not a location."}
    
    game_state.npc_locations[npc_key] = new_location
    
    return {
        "success": True,
        "reason": f"{npc_key} moved to {new_location}."
    }


def list_scene_entities(game_state: GameState, story_graph: StoryGraph) -> dict[str, Any]:
    """List entities relevant to the player's current scene, including the player entity."""
    context = get_current_context(game_state, story_graph)
    registry = ensure_entity_registry(game_state, story_graph)

    names = [
        "Player",
        context.get("location"),
        *(context.get("npcs_here") or []),
        *(context.get("items_here") or []),
    ]

    seen: set[str] = set()
    entities: list[dict[str, Any]] = []
    for name in names:
        if not name:
            continue
        norm = _normalize_key(name)
        if norm in seen:
            continue
        seen.add(norm)
        entity = registry.get(norm)
        if entity is None:
            continue
        entities.append(
            {
                "key": entity.key,
                "entity_type": entity.entity_type,
                "location": entity.get_location(),
                "memory_count": entity.memory_count,
                "skills": entity.list_skill_names(),
            }
        )

    return {
        "success": True,
        "player_location": game_state.player_location,
        "scene_entities": entities,
    }


def get_entity_state(
    entity_key: str,
    include_memory_preview: bool = False,
    memory_preview: int = 3,
    game_state: GameState | None = None,
    story_graph: StoryGraph | None = None,
) -> dict[str, Any]:
    """
    Read entity state variables (location/skills/stats/memory counts/etc).
    `game_state` and `story_graph` are injected by execute_tool and should not be model-provided.
    """
    if game_state is None or story_graph is None:
        return {"success": False, "reason": "Missing game_state/story_graph context."}

    entity = _find_entity(entity_key, game_state, story_graph)
    if entity is None:
        return {"success": False, "reason": f"Entity '{entity_key}' not found."}

    return {
        "success": True,
        "entity": _entity_public_view(
            entity,
            include_memory_preview=bool(include_memory_preview),
            memory_preview=max(0, int(memory_preview)),
        ),
    }


def retrieve_memory_tool(
    entity_name: str,
    context: str,
    top_n: int = 4,
    game_state: GameState | None = None,
    story_graph: StoryGraph | None = None,
) -> dict[str, Any]:
    """Retrieve relevant memory snippets for a registered entity."""
    if game_state is None or story_graph is None:
        return {"success": False, "message": "Missing game_state/story_graph context.", "memories": []}

    entity = _find_entity(entity_name, game_state, story_graph)
    if entity is None:
        return {
            "success": False,
            "message": f"Entity '{entity_name}' is not registered.",
            "memories": [],
        }

    hits = entity.search_memory(context, top_n=max(1, int(top_n)))
    return {
        "success": True,
        "entity_name": entity.name,
        "memory_backend": DynamicSentenceMemory.backend_status(),
        "memories": [{"sentence": hit.sentence, "score": float(hit.score)} for hit in hits],
    }


def write_memory_tool(
    entity_name: str,
    memory: str = "",
    relevance: float = 100.0,
    context: str = "",
    game_state: GameState | None = None,
    story_graph: StoryGraph | None = None,
) -> dict[str, Any]:
    """Write a new sentence memory into an entity memory store."""
    if game_state is None or story_graph is None:
        return {"success": False, "message": "Missing game_state/story_graph context."}

    entity = _find_entity(entity_name, game_state, story_graph)
    if entity is None:
        return {
            "success": False,
            "message": f"Entity '{entity_name}' is not registered.",
        }

    text = str(memory or context or "").strip()
    if not text:
        return {"success": False, "message": "memory/context cannot be empty."}

    entity.add_memory(text)
    return {
        "success": True,
        "entity_name": entity.name,
        "memory": text,
        "relevance": float(relevance),
        "memory_count": entity.memory_count,
    }


def roll_dice(
    sides: int = 20,
    count: int = 1,
    modifier: int = 0,
    label: str = "",
    game_state: GameState | None = None,
    story_graph: StoryGraph | None = None,
) -> dict[str, Any]:
    """Roll one or more dice and return a structured result."""
    # game_state/story_graph accepted for dispatcher consistency, not required.
    _ = game_state, story_graph
    sides = int(sides)
    count = int(count)
    modifier = int(modifier)

    if sides < 2 or sides > 1000:
        return {"success": False, "reason": "sides must be between 2 and 1000."}
    if count < 1 or count > 20:
        return {"success": False, "reason": "count must be between 1 and 20."}

    rolls = [random.randint(1, sides) for _ in range(count)]
    subtotal = sum(rolls)
    total = subtotal + modifier
    return {
        "success": True,
        "label": str(label or ""),
        "formula": f"{count}d{sides}{modifier:+d}" if modifier else f"{count}d{sides}",
        "rolls": rolls,
        "subtotal": subtotal,
        "modifier": modifier,
        "total": total,
    }


def skill_check(
    entity_key: str,
    skill: str,
    dc: int,
    context: str = "",
    top_memory: int = 0,
    _manual_roll: int | None = None,
    game_state: GameState | None = None,
    story_graph: StoryGraph | None = None,
) -> dict[str, Any]:
    """Resolve a D20-style skill check against an entity's stored skill/stat values."""
    if game_state is None or story_graph is None:
        return {"success": False, "reason": "Missing game_state/story_graph context."}

    entity = _find_entity(entity_key, game_state, story_graph)
    if entity is None:
        return {"success": False, "reason": f"Entity '{entity_key}' not found."}

    skill_key = _normalize_key(skill).replace(" ", "_")
    target_dc = int(dc)
    if target_dc < 1 or target_dc > 40:
        return {"success": False, "reason": "dc must be between 1 and 40."}

    skill_modifier = entity.get_skill(skill_key)
    stat_key = SKILL_TO_STAT.get(skill_key)
    stat_modifier = entity.get_stat_modifier(stat_key) if stat_key else 0

    if skill_modifier is None:
        skill_modifier = stat_modifier

    if _manual_roll is None:
        roll_payload = roll_dice(sides=20, count=1, modifier=int(skill_modifier), label=f"{entity.key}:{skill_key}")
    else:
        roll_value = int(_manual_roll)
        if roll_value < 1 or roll_value > 20:
            return {"success": False, "reason": "manual d20 roll must be between 1 and 20."}
        subtotal = roll_value
        total = subtotal + int(skill_modifier)
        roll_payload = {
            "success": True,
            "label": f"{entity.key}:{skill_key}",
            "formula": f"1d20{int(skill_modifier):+d}" if int(skill_modifier) else "1d20",
            "rolls": [roll_value],
            "subtotal": subtotal,
            "modifier": int(skill_modifier),
            "total": total,
        }
    if not roll_payload.get("success"):
        return roll_payload

    total = int(roll_payload["total"])
    success = total >= target_dc

    memory_hits: list[dict[str, Any]] = []
    if int(top_memory) > 0 and str(context or "").strip():
        hits = entity.search_memory(str(context), top_n=max(1, int(top_memory)))
        memory_hits = [{"sentence": hit.sentence, "score": float(hit.score)} for hit in hits]

    entry = {
        "entity_key": entity.key,
        "skill": skill_key,
        "stat": stat_key,
        "dc": target_dc,
        "modifier": int(skill_modifier),
        "roll": int(roll_payload["rolls"][0]),
        "total": total,
        "success": bool(success),
        "context": str(context or "").strip(),
    }
    _skill_check_log(game_state).append(entry)

    return {
        "success": True,
        "check": entry,
        "memory_hits": memory_hits,
        "skill_check_log_size": len(_skill_check_log(game_state)),
    }


def get_recent_skill_checks(limit: int = 5, game_state: GameState | None = None, story_graph: StoryGraph | None = None) -> dict[str, Any]:
    """Read recent skill check results from the session log."""
    _ = story_graph
    if game_state is None:
        return {"success": False, "reason": "Missing game_state context."}
    lim = max(1, min(50, int(limit)))
    log = _skill_check_log(game_state)
    return {"success": True, "checks": log[-lim:]}


TURN_TODO_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "set_turn_todo",
            "description": "Create or replace the turn todo list for the mechanics phase.",
            "parameters": {
                "type": "object",
                "properties": {
                    "plan_summary": {"type": "string"},
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "task": {"type": "string"},
                                "requires_tool": {"type": "boolean"},
                                "tool_name": {
                                    "type": "string",
                                    "enum": [
                                        "",
                                        "check_can_interact",
                                        "get_current_context",
                                        "move_to_location",
                                        "list_scene_entities",
                                        "get_entity_state",
                                        "retrieve_memory_tool",
                                        "write_memory_tool",
                                        "roll_dice",
                                        "skill_check",
                                        "get_recent_skill_checks",
                                    ],
                                },
                                "arguments_hint": {"type": "object"},
                            },
                            "required": ["task"],
                        },
                    },
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_turn_todo",
            "description": "Read the current turn todo list and status counts.",
            "parameters": {
                "type": "object",
                "properties": {"include_completed": {"type": "boolean"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_todo_item_status",
            "description": "Mark a todo item as pending/in_progress/done/skipped/blocked with a resolution note.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer", "minimum": 1},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "done", "skipped", "blocked"],
                    },
                    "resolution": {"type": "string"},
                    "used_tool": {"type": "boolean"},
                },
                "required": ["item_id", "status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_turn_progress",
            "description": "Read orchestration progress for the current turn.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_turn_note",
            "description": "Record a short note for narration handoff.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
]


# Read-only tools for validation
VALIDATE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_can_interact",
            "description": "Check if player can interact with an entity. Use this before narrating any interaction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_key": {
                        "type": "string",
                        "description": "Entity key to check (e.g., 'Mitch', 'Town Square')"
                    }
                },
                "required": ["entity_key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_context",
            "description": "Get details about player's current location.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]

# Agent-loop tool catalog (read + state/memory/mechanics tools)
TOOL_DEFINITIONS = [
    *VALIDATE_TOOLS,  # Include the read-only tools
    {
        "type": "function",
        "function": {
            "name": "move_to_location",
            "description": "Move player to a connected location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_key": {
                        "type": "string",
                        "description": "Location key to move to"
                    }
                },
                "required": ["location_key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "move_npc",
            "description": "Move an NPC to a different location (DM only, for story progression).",
            "parameters": {
                "type": "object",
                "properties": {
                    "npc_key": {"type": "string", "description": "NPC key"},
                    "new_location": {"type": "string", "description": "Destination location"}
                },
                "required": ["npc_key", "new_location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_scene_entities",
            "description": "List entities in the current scene and summarize their state.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity_state",
            "description": "Read detailed state variables for an entity (location, skills, stats, memory count).",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_key": {"type": "string", "description": "Entity key or name."},
                    "include_memory_preview": {"type": "boolean"},
                    "memory_preview": {"type": "integer", "minimum": 0, "maximum": 20}
                },
                "required": ["entity_key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_memory_tool",
            "description": "Retrieve relevant memory snippets for an entity using semantic search when available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {"type": "string", "description": "Entity name or key."},
                    "context": {"type": "string", "description": "Query context for similarity search."},
                    "top_n": {"type": "integer", "minimum": 1, "maximum": 20}
                },
                "required": ["entity_name", "context"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_memory_tool",
            "description": "Write a new memory sentence into an entity memory store.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {"type": "string", "description": "Entity name or key."},
                    "memory": {"type": "string", "description": "Sentence or fact to store."},
                    "context": {"type": "string", "description": "Alias for memory (notebook compatibility)."},
                    "relevance": {"type": "number", "minimum": 0, "maximum": 1000}
                },
                "required": ["entity_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "roll_dice",
            "description": "Roll one or more dice with an optional modifier.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sides": {"type": "integer", "minimum": 2, "maximum": 1000},
                    "count": {"type": "integer", "minimum": 1, "maximum": 20},
                    "modifier": {"type": "integer", "minimum": -100, "maximum": 100},
                    "label": {"type": "string"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "skill_check",
            "description": "Resolve a D20-style skill check for an entity (use 'Player' for player checks).",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_key": {"type": "string", "description": "Entity key, e.g. 'Player' or an NPC name."},
                    "skill": {"type": "string", "description": "Skill name such as perception, investigation, persuasion."},
                    "dc": {"type": "integer", "minimum": 1, "maximum": 40},
                    "context": {"type": "string", "description": "Optional situational context for the check."},
                    "top_memory": {"type": "integer", "minimum": 0, "maximum": 10}
                },
                "required": ["entity_key", "skill", "dc"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_skill_checks",
            "description": "Read recent skill check results from the session log.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50}
                },
                "required": []
            }
        }
    }
]


def execute_tool(tool_name: str, arguments: dict[str, Any], game_state: GameState, story_graph: StoryGraph) -> dict[str, Any]:
    """Execute a tool by name."""
    if tool_name == "set_turn_todo":
        return set_turn_todo(
            game_state=game_state,
            story_graph=story_graph,
            **arguments,
        )
    elif tool_name == "get_turn_todo":
        return get_turn_todo(
            game_state=game_state,
            story_graph=story_graph,
            **arguments,
        )
    elif tool_name == "set_todo_item_status":
        return set_todo_item_status(
            game_state=game_state,
            story_graph=story_graph,
            **arguments,
        )
    elif tool_name == "get_turn_progress":
        return get_turn_progress(
            game_state=game_state,
            story_graph=story_graph,
            **arguments,
        )
    elif tool_name == "add_turn_note":
        return add_turn_note(
            game_state=game_state,
            story_graph=story_graph,
            **arguments,
        )
    elif tool_name == "check_can_interact":
        return check_can_interact(arguments["entity_key"], game_state, story_graph)
    elif tool_name == "move_to_location":
        return move_to_location(arguments["location_key"], game_state, story_graph)
    elif tool_name == "get_current_context":
        return get_current_context(game_state, story_graph)
    elif tool_name == "move_npc":
        return move_npc(arguments["npc_key"], arguments["new_location"], game_state, story_graph)
    elif tool_name == "list_scene_entities":
        return list_scene_entities(game_state, story_graph)
    elif tool_name == "get_entity_state":
        return get_entity_state(
            game_state=game_state,
            story_graph=story_graph,
            **arguments,
        )
    elif tool_name == "retrieve_memory_tool":
        return retrieve_memory_tool(
            game_state=game_state,
            story_graph=story_graph,
            **arguments,
        )
    elif tool_name == "write_memory_tool":
        return write_memory_tool(
            game_state=game_state,
            story_graph=story_graph,
            **arguments,
        )
    elif tool_name == "roll_dice":
        return roll_dice(
            game_state=game_state,
            story_graph=story_graph,
            **arguments,
        )
    elif tool_name == "skill_check":
        return skill_check(
            game_state=game_state,
            story_graph=story_graph,
            **arguments,
        )
    elif tool_name == "get_recent_skill_checks":
        return get_recent_skill_checks(
            game_state=game_state,
            story_graph=story_graph,
            **arguments,
        )
    else:
        return {"success": False, "reason": f"Unknown tool: {tool_name}"}

__all__ = [
    "Entity",
    "DynamicSentenceMemory",
    "check_can_interact",
    "move_to_location",
    "get_current_context",
    "move_npc",
    "list_scene_entities",
    "get_entity_state",
    "retrieve_memory_tool",
    "write_memory_tool",
    "roll_dice",
    "skill_check",
    "get_recent_skill_checks",
    "ensure_entity_registry",
    "bind_turn_orchestration_ctx",
    "clear_turn_orchestration_ctx",
    "TODO_ACTIVE_STATUSES",
    "TODO_FINAL_STATUSES",
    "TODO_ALLOWED_STATUSES",
    "TURN_TODO_TOOL_DEFINITIONS",
    "TOOL_DEFINITIONS",
    "VALIDATE_TOOLS",
    "execute_tool",
]

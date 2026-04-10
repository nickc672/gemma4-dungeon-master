from __future__ import annotations

from typing import Any

from .story import GameState
from .tool_runtime import ensure_entity_registry, get_runtime_world_model, normalize_key


def _resolve_target_key(model, raw_key: str) -> str:
    candidate = str(raw_key or "").strip()
    if not candidate:
        return ""
    if model.get_location(candidate) is not None:
        return model.get_location(candidate).key
    if model.get_entity(candidate) is not None:
        return model.get_entity(candidate).key
    if model.get_item(candidate) is not None:
        return model.get_item(candidate).key

    needle = normalize_key(candidate)
    for location in model.locations.values():
        if needle in normalize_key(location.key) or needle in normalize_key(location.name):
            return location.key
    for entity in model.entities.values():
        if needle in normalize_key(entity.key) or needle in normalize_key(entity.name):
            return entity.key
    for item in model.items.values():
        if needle in normalize_key(item.key) or needle in normalize_key(item.name):
            return item.key
    return ""


def check_can_interact(entity_key: str = "", game_state: GameState | None = None) -> dict[str, object]:
    if game_state is None:
        return {"success": False, "can_interact": False, "reason": "Missing game_state context."}
    model = get_runtime_world_model(game_state)
    player_loc = game_state.player_location
    resolved_key = _resolve_target_key(model, entity_key) or player_loc
    if not resolved_key:
        return {
            "success": True,
            "can_interact": False,
            "reason": "No interactable target was provided.",
            "nearby": model.scene_snapshot(player_loc),
        }

    entity_key = resolved_key
    location = model.get_location(entity_key)
    if location is not None:
        current_location = model.get_location(player_loc)
        if current_location is None:
            return {"success": False, "can_interact": False, "reason": "Invalid player location"}
        if location.key == player_loc:
            return {
                "success": True,
                "can_interact": True,
                "entity_type": "location",
                "reason": "You are already at this location.",
            }
        if location.key in current_location.connections:
            return {
                "success": True,
                "can_interact": True,
                "entity_type": "location",
                "reason": f"{location.key} is accessible from here.",
            }
        return {
            "success": True,
            "can_interact": False,
            "entity_type": "location",
            "reason": f"{location.key} is not connected to {player_loc}.",
        }

    entity = model.get_entity(entity_key)
    if entity is not None:
        if entity.key == "Player":
            return {
                "success": True,
                "can_interact": False,
                "entity_type": "player",
                "reason": "The player cannot interact with themselves as a separate target.",
            }
        if entity.location == player_loc:
            return {
                "success": True,
                "can_interact": True,
                "entity_type": entity.entity_type,
                "reason": f"{entity.key} is here.",
            }
        return {
            "success": True,
            "can_interact": False,
            "entity_type": entity.entity_type,
            "reason": f"{entity.key} is at {entity.location}.",
        }

    item = model.get_item(entity_key)
    if item is not None:
        if item.is_at_location(player_loc):
            return {
                "success": True,
                "can_interact": True,
                "entity_type": "item",
                "reason": f"{item.key} is here.",
            }
        if item.holder_kind == "entity":
            holder = model.get_entity(item.holder_key)
            if holder is not None and holder.location == player_loc:
                return {
                    "success": True,
                    "can_interact": True,
                    "entity_type": "item",
                    "reason": f"{item.key} is being carried by {holder.key}.",
                }
        return {
            "success": True,
            "can_interact": False,
            "entity_type": "item",
            "reason": f"{item.key} is at {item.holder_key}.",
        }

    return {
        "success": True,
        "can_interact": False,
        "reason": f"Entity '{entity_key}' does not exist.",
        "nearby": model.scene_snapshot(player_loc),
    }


def move_to_location(location_key: str = "", game_state: GameState | None = None) -> dict[str, object]:
    if game_state is None:
        return {"success": False, "new_location": None, "reason": "Missing game_state context."}
    model = get_runtime_world_model(game_state)
    if not str(location_key or "").strip():
        return {
            "success": True,
            "new_location": game_state.player_location,
            "reason": "No destination provided. Staying at current location.",
        }
    resolved_destination = _resolve_target_key(model, location_key)
    if resolved_destination and model.get_location(resolved_destination) is not None:
        location_key = resolved_destination
    location = model.get_location(location_key)
    if location is None:
        return {
            "success": False,
            "new_location": None,
            "reason": f"Location '{location_key}' does not exist.",
        }

    current_location = model.get_location(game_state.player_location)
    if current_location is None:
        return {"success": False, "new_location": None, "reason": "Invalid current location."}
    if location_key == game_state.player_location:
        return {"success": True, "new_location": location_key, "reason": "You are already here."}
    if location_key not in current_location.connections:
        return {
            "success": False,
            "new_location": None,
            "reason": f"Cannot move to {location_key}. Not connected to {game_state.player_location}.",
        }

    if not model.move_entity("Player", location_key):
        return {"success": False, "new_location": None, "reason": "Player entity is missing from the world model."}

    game_state.player_location = location.key
    game_state.discovered_keys.add(location_key)
    return {"success": True, "new_location": location.key, "reason": f"Moved to {location.key}."}


def get_current_context(game_state: GameState) -> dict[str, object]:
    model = get_runtime_world_model(game_state)
    scene = model.scene_snapshot(game_state.player_location)

    npcs_here: list[str] = []
    for actor_key in scene.get("actors_here", []):
        if normalize_key(actor_key) == "player":
            continue
        actor = model.get_entity(actor_key)
        if actor is not None and actor.entity_type == "npc":
            npcs_here.append(actor.key)

    return {
        "location": str(scene.get("location") or game_state.player_location),
        "description": str(scene.get("description") or "Unknown location"),
        "connected_locations": list(scene.get("connections") or []),
        "npcs_here": npcs_here,
        "items_here": list(scene.get("items_here") or []),
    }


def move_npc(npc_key: str = "", new_location: str = "", game_state: GameState | None = None) -> dict[str, object]:
    if game_state is None:
        return {"success": False, "reason": "Missing game_state context."}
    model = get_runtime_world_model(game_state)
    if not str(npc_key or "").strip() or not str(new_location or "").strip():
        return {"success": True, "reason": "Missing npc_key or new_location. No NPC movement applied."}
    resolved_npc = _resolve_target_key(model, npc_key)
    resolved_location = _resolve_target_key(model, new_location)
    npc = model.get_entity(resolved_npc or npc_key)
    if npc is None:
        return {"success": False, "reason": f"NPC '{npc_key}' does not exist."}
    if npc.entity_type != "npc":
        return {"success": False, "reason": f"'{npc_key}' is not an NPC."}
    location = model.get_location(resolved_location or new_location)
    if location is None:
        return {"success": False, "reason": f"Location '{new_location}' does not exist."}

    model.move_entity(npc.key, location.key)
    game_state.npc_locations[npc.key] = location.key
    return {"success": True, "reason": f"{npc.key} moved to {location.key}."}


def list_scene_entities(game_state: GameState) -> dict[str, object]:
    model = get_runtime_world_model(game_state)
    registry = ensure_entity_registry(game_state)
    scene = model.scene_snapshot(game_state.player_location)
    entities: list[dict[str, Any]] = []

    location = model.get_location(str(scene.get("location") or game_state.player_location))
    if location is not None:
        entities.append(
            {
                "key": location.key,
                "entity_type": "location",
                "location": location.key,
                "memory_count": 0,
                "skills": [],
                "connections": list(location.connections),
            }
        )

    for actor_key in scene.get("actors_here", []):
        actor = registry.get(normalize_key(actor_key))
        if actor is None:
            continue
        entities.append(
            {
                "key": actor.key,
                "entity_type": actor.entity_type,
                "location": actor.get_location(),
                "memory_count": actor.memory_count,
                "skills": actor.list_skill_names(),
                "inventory": list(actor.inventory),
            }
        )

    for item_key in scene.get("items_here", []):
        item = model.get_item(item_key)
        if item is None:
            continue
        entities.append(
            {
                "key": item.key,
                "entity_type": "item",
                "location": scene.get("location"),
                "memory_count": 0,
                "skills": [],
                "portable": bool(item.portable),
            }
        )

    return {
        "success": True,
        "player_location": game_state.player_location,
        "scene_entities": entities,
    }


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
                        "description": "Entity key to check (e.g., 'Mitch', 'Town Square')",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_context",
            "description": "Get details about player's current location.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

SCENE_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "move_to_location",
            "description": "Move player to a connected location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_key": {"type": "string", "description": "Location key to move to"}
                },
                "required": [],
            },
        },
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
                    "new_location": {"type": "string", "description": "Destination location"},
                },
                "required": ["npc_key", "new_location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_scene_entities",
            "description": "List entities in the current scene and summarize their state.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


__all__ = [
    "SCENE_TOOL_DEFINITIONS",
    "VALIDATE_TOOLS",
    "check_can_interact",
    "get_current_context",
    "list_scene_entities",
    "move_npc",
    "move_to_location",
]

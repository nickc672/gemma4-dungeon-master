from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .entity import Entity
from .item import Item
from .location import Location
from .story import GameState
from .tool_runtime import get_runtime_world_model, save_runtime_world_checkpoint
from .world_model import WORLD_MODEL_DATA_DIR, WorldModel, build_world_model


def _resolve_data_dir(world_model_data_dir: str = "") -> Path:
    if str(world_model_data_dir or "").strip():
        return Path(str(world_model_data_dir)).expanduser().resolve()
    return WORLD_MODEL_DATA_DIR


def _load_model(world_model_data_dir: str = "", game_state: GameState | None = None) -> WorldModel:
    if game_state is not None:
        return get_runtime_world_model(game_state)
    return build_world_model(data_dir=_resolve_data_dir(world_model_data_dir))


def _save_model(
    model: WorldModel,
    world_model_data_dir: str = "",
    *,
    game_state: GameState | None = None,
    checkpoint_name: str = "",
) -> str:
    if game_state is not None:
        checkpoint_dir = save_runtime_world_checkpoint(game_state, checkpoint_name=checkpoint_name)
        return str(checkpoint_dir) if checkpoint_dir is not None else ""
    save_dir = _resolve_data_dir(world_model_data_dir)
    model.save(data_dir=save_dir)
    return str(save_dir)


def get_world_story(world_model_data_dir: str = "", game_state: GameState | None = None) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    return {"success": True, "story": model.story_record()}


def write_world_story(
    starting_location: str | None = None,
    starting_state: str | None = None,
    beat_list: list[str] | None = None,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    model.set_story(
        starting_location=starting_location,
        starting_state=starting_state,
        beat_list=beat_list,
    )
    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors}
    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )
    return {"success": True, "story": model.story_record(), "save_path": save_path}


def list_world_locations(world_model_data_dir: str = "", game_state: GameState | None = None) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    return {"success": True, "locations": model.list_location_records()}


def get_world_location(
    location_key: str,
    world_model_data_dir: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    location = model.get_location(location_key)
    if location is None:
        return {"success": False, "reason": f"Unknown location '{location_key}'."}
    return {"success": True, "location": location.to_record()}


def upsert_world_location(
    location_key: str,
    name: str = "",
    description: str = "",
    connections: list[str] | None = None,
    tags: list[str] | None = None,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    existing = model.get_location(location_key)
    location = Location(
        key=location_key,
        name=name or (existing.name if existing else location_key),
        description=description or (existing.description if existing else ""),
        connections=[str(value) for value in (connections if connections is not None else (existing.connections if existing else []))],
        tags=[str(value) for value in (tags if tags is not None else (existing.tags if existing else []))],
    )
    model.add_location(location)
    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors}
    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )
    return {"success": True, "location": location.to_record(), "save_path": save_path}


def connect_world_locations(
    location_key: str,
    other_location_key: str,
    bidirectional: bool = True,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    if not model.connect_locations(location_key, other_location_key, bidirectional=bool(bidirectional)):
        return {"success": False, "reason": "Both locations must exist before they can be connected."}
    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors}
    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )
    return {
        "success": True,
        "scene": model.scene_snapshot(location_key),
        "other_scene": model.scene_snapshot(other_location_key),
        "save_path": save_path,
    }


def get_world_scene(
    location_key: str,
    world_model_data_dir: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    return {"success": True, "scene": model.scene_snapshot(location_key)}


def list_world_entities(
    entity_type: str = "",
    world_model_data_dir: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    return {"success": True, "entities": model.list_entity_records(entity_type=entity_type or None)}


def get_world_entity(
    entity_key: str,
    world_model_data_dir: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    entity = model.get_entity(entity_key)
    if entity is None:
        return {"success": False, "reason": f"Unknown entity '{entity_key}'."}
    return {"success": True, "entity": entity.to_record(), "inventory": list(entity.inventory)}


def upsert_world_entity(
    entity_key: str,
    name: str = "",
    entity_type: str = "npc",
    description: str = "",
    location: str = "",
    skills: dict[str, int] | None = None,
    stats: dict[str, int] | None = None,
    tags: list[str] | None = None,
    memory: list[str] | None = None,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    existing = model.get_entity(entity_key)
    payload = {
        "key": entity_key,
        "name": name or (existing.name if existing else entity_key),
        "entity_type": entity_type or (existing.entity_type if existing else "npc"),
        "description": description or (existing.description if existing else ""),
        "location": location or (existing.location if existing else model.starting_location),
        "skills": skills if skills is not None else (dict(existing.skills) if existing else {}),
        "stats": stats if stats is not None else (dict(existing.stats) if existing else {}),
        "tags": tags if tags is not None else (list(existing.tags) if existing else []),
        "memory": memory if memory is not None else (list(existing.memory.sentences) if existing else []),
    }
    entity = Entity.from_record(payload)
    model.add_entity(entity)
    model.sync_actor_inventories()
    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors}
    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )
    return {"success": True, "entity": entity.to_record(), "save_path": save_path}


def move_world_entity(
    entity_key: str,
    location_key: str,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    if not model.move_entity(entity_key, location_key):
        return {"success": False, "reason": "Entity and location must both exist."}
    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors}
    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )
    entity = model.get_entity(entity_key)
    return {"success": True, "entity": entity.to_record() if entity else None, "save_path": save_path}


def list_world_items(
    holder_kind: str = "",
    holder_key: str = "",
    world_model_data_dir: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    return {
        "success": True,
        "items": model.list_item_records(
            holder_kind=holder_kind or None,
            holder_key=holder_key or None,
        ),
    }


def get_world_item(
    item_key: str,
    world_model_data_dir: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    item = model.get_item(item_key)
    if item is None:
        return {"success": False, "reason": f"Unknown item '{item_key}'."}
    return {"success": True, "item": item.to_record()}


def upsert_world_item(
    item_key: str,
    name: str = "",
    description: str = "",
    holder_kind: str = "",
    holder_key: str = "",
    portable: bool | None = None,
    tags: list[str] | None = None,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    existing = model.get_item(item_key)
    item = Item.from_record(
        {
            "key": item_key,
            "name": name or (existing.name if existing else item_key),
            "description": description or (existing.description if existing else ""),
            "holder_kind": holder_kind or (existing.holder_kind if existing else "location"),
            "holder_key": holder_key or (existing.holder_key if existing else model.starting_location),
            "portable": bool(portable) if portable is not None else (existing.portable if existing else True),
            "tags": tags if tags is not None else (list(existing.tags) if existing else []),
        }
    )
    model.add_item(item)
    model.sync_actor_inventories()
    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors}
    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )
    return {"success": True, "item": item.to_record(), "save_path": save_path}


def move_world_item(
    item_key: str,
    holder_kind: str,
    holder_key: str,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    normalized_kind = str(holder_kind or "").strip().lower()
    if normalized_kind == "location":
        ok = model.move_item_to_location(item_key, holder_key)
    elif normalized_kind == "entity":
        ok = model.move_item_to_entity(item_key, holder_key)
    else:
        return {"success": False, "reason": "holder_kind must be 'location' or 'entity'."}
    if not ok:
        return {"success": False, "reason": "Item and target holder must both exist."}
    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors}
    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )
    item = model.get_item(item_key)
    return {"success": True, "item": item.to_record() if item else None, "save_path": save_path}


def validate_world_model(world_model_data_dir: str = "", game_state: GameState | None = None) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    errors = model.validate()
    return {"success": not errors, "errors": errors}


WORLD_MODEL_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_world_story",
            "description": "Read starting story information for the current world model.",
            "parameters": {"type": "object", "properties": {"world_model_data_dir": {"type": "string"}}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_world_story",
            "description": "Update starting story information for the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "starting_location": {"type": "string"},
                    "starting_state": {"type": "string"},
                    "beat_list": {"type": "array", "items": {"type": "string"}},
                    "world_model_data_dir": {"type": "string"},
                    "checkpoint_name": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_world_locations",
            "description": "List all locations in the current world model.",
            "parameters": {"type": "object", "properties": {"world_model_data_dir": {"type": "string"}}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_world_location",
            "description": "Read a single location from the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_key": {"type": "string"},
                    "world_model_data_dir": {"type": "string"},
                },
                "required": ["location_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_world_location",
            "description": "Create or update a location in the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_key": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "connections": {"type": "array", "items": {"type": "string"}},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "world_model_data_dir": {"type": "string"},
                    "checkpoint_name": {"type": "string"},
                },
                "required": ["location_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "connect_world_locations",
            "description": "Connect two locations in the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_key": {"type": "string"},
                    "other_location_key": {"type": "string"},
                    "bidirectional": {"type": "boolean"},
                    "world_model_data_dir": {"type": "string"},
                    "checkpoint_name": {"type": "string"},
                },
                "required": ["location_key", "other_location_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_world_scene",
            "description": "Get a scene snapshot from the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_key": {"type": "string"},
                    "world_model_data_dir": {"type": "string"},
                },
                "required": ["location_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_world_entities",
            "description": "List actors in the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string"},
                    "world_model_data_dir": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_world_entity",
            "description": "Read a single actor from the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_key": {"type": "string"},
                    "world_model_data_dir": {"type": "string"},
                },
                "required": ["entity_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_world_entity",
            "description": "Create or update an actor in the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_key": {"type": "string"},
                    "name": {"type": "string"},
                    "entity_type": {"type": "string"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "skills": {"type": "object"},
                    "stats": {"type": "object"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "memory": {"type": "array", "items": {"type": "string"}},
                    "world_model_data_dir": {"type": "string"},
                    "checkpoint_name": {"type": "string"},
                },
                "required": ["entity_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_world_entity",
            "description": "Move an actor to a different location in the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_key": {"type": "string"},
                    "location_key": {"type": "string"},
                    "world_model_data_dir": {"type": "string"},
                    "checkpoint_name": {"type": "string"},
                },
                "required": ["entity_key", "location_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_world_items",
            "description": "List items in the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "holder_kind": {"type": "string"},
                    "holder_key": {"type": "string"},
                    "world_model_data_dir": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_world_item",
            "description": "Read a single item from the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_key": {"type": "string"},
                    "world_model_data_dir": {"type": "string"},
                },
                "required": ["item_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_world_item",
            "description": "Create or update an item in the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_key": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "holder_kind": {"type": "string"},
                    "holder_key": {"type": "string"},
                    "portable": {"type": "boolean"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "world_model_data_dir": {"type": "string"},
                    "checkpoint_name": {"type": "string"},
                },
                "required": ["item_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_world_item",
            "description": "Move an item to a location or actor holder in the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_key": {"type": "string"},
                    "holder_kind": {"type": "string", "enum": ["location", "entity"]},
                    "holder_key": {"type": "string"},
                    "world_model_data_dir": {"type": "string"},
                    "checkpoint_name": {"type": "string"},
                },
                "required": ["item_key", "holder_kind", "holder_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_world_model",
            "description": "Validate world-model references and structure.",
            "parameters": {"type": "object", "properties": {"world_model_data_dir": {"type": "string"}}, "required": []},
        },
    },
]


def execute_world_model_tool(
    tool_name: str,
    arguments: dict[str, Any],
    game_state: GameState | None = None,
) -> dict[str, Any]:
    if tool_name == "get_world_story":
        return get_world_story(game_state=game_state, **arguments)
    if tool_name == "write_world_story":
        return write_world_story(game_state=game_state, **arguments)
    if tool_name == "list_world_locations":
        return list_world_locations(game_state=game_state, **arguments)
    if tool_name == "get_world_location":
        return get_world_location(game_state=game_state, **arguments)
    if tool_name == "upsert_world_location":
        return upsert_world_location(game_state=game_state, **arguments)
    if tool_name == "connect_world_locations":
        return connect_world_locations(game_state=game_state, **arguments)
    if tool_name == "get_world_scene":
        return get_world_scene(game_state=game_state, **arguments)
    if tool_name == "list_world_entities":
        return list_world_entities(game_state=game_state, **arguments)
    if tool_name == "get_world_entity":
        return get_world_entity(game_state=game_state, **arguments)
    if tool_name == "upsert_world_entity":
        return upsert_world_entity(game_state=game_state, **arguments)
    if tool_name == "move_world_entity":
        return move_world_entity(game_state=game_state, **arguments)
    if tool_name == "list_world_items":
        return list_world_items(game_state=game_state, **arguments)
    if tool_name == "get_world_item":
        return get_world_item(game_state=game_state, **arguments)
    if tool_name == "upsert_world_item":
        return upsert_world_item(game_state=game_state, **arguments)
    if tool_name == "move_world_item":
        return move_world_item(game_state=game_state, **arguments)
    if tool_name == "validate_world_model":
        return validate_world_model(game_state=game_state, **arguments)
    return {"success": False, "reason": f"Unknown world-model tool: {tool_name}"}


__all__ = [
    "WORLD_MODEL_TOOL_DEFINITIONS",
    "execute_world_model_tool",
    "get_world_story",
    "write_world_story",
    "list_world_locations",
    "get_world_location",
    "upsert_world_location",
    "connect_world_locations",
    "get_world_scene",
    "list_world_entities",
    "get_world_entity",
    "upsert_world_entity",
    "move_world_entity",
    "list_world_items",
    "get_world_item",
    "upsert_world_item",
    "move_world_item",
    "validate_world_model",
]

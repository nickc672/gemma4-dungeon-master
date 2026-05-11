from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .entity import Entity
from .item import Item
from .location import Location
from .story import GameState
from .tool_runtime import (
    get_runtime_world_model,
    normalize_key,
    register_entity_aliases,
    require_turn_orchestration_ctx,
    save_runtime_world_checkpoint,
)
from .world_model import WORLD_MODEL_DATA_DIR, WorldModel, build_world_model


# Per-turn caps to prevent runaway creation.
MAX_ENTITY_CREATIONS_PER_TURN = 2
MAX_ITEM_CREATIONS_PER_TURN = 3

# Reserved entity keys that must never be overwritten at runtime.
_PROTECTED_KEYS = {"player"}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _first_location_key(model: WorldModel) -> str:
    if not model.locations:
        return ""
    return sorted(model.locations.values(), key=lambda value: value.key.lower())[0].key


def _resolve_location_candidate(model: WorldModel, location_key: str) -> str:
    candidate = str(location_key or "").strip()
    if not candidate:
        return ""
    location = model.get_location(candidate)
    if location is not None:
        return location.key

    needle = _normalize_text(candidate)
    for location_value in model.locations.values():
        if needle in _normalize_text(location_value.key) or needle in _normalize_text(location_value.name):
            return location_value.key
    return ""


def _resolve_entity_candidate(model: WorldModel, entity_key: str) -> str:
    candidate = str(entity_key or "").strip()
    if not candidate:
        return ""
    entity = model.get_entity(candidate)
    if entity is not None:
        return entity.key

    needle = _normalize_text(candidate)
    for entity_value in model.entities.values():
        if needle in _normalize_text(entity_value.key) or needle in _normalize_text(entity_value.name):
            return entity_value.key
    return ""


def _resolve_item_candidate(model: WorldModel, item_key: str) -> str:
    candidate = str(item_key or "").strip()
    if not candidate:
        return ""
    item = model.get_item(candidate)
    if item is not None:
        return item.key

    needle = _normalize_text(candidate)
    for item_value in model.items.values():
        if needle in _normalize_text(item_value.key) or needle in _normalize_text(item_value.name):
            return item_value.key
    return ""


def _default_scene_location(model: WorldModel, game_state: GameState | None) -> str:
    if game_state is not None and str(game_state.player_location or "").strip():
        resolved = _resolve_location_candidate(model, game_state.player_location)
        if resolved:
            return resolved
    if model.starting_location:
        resolved = _resolve_location_candidate(model, model.starting_location)
        if resolved:
            return resolved
    return _first_location_key(model)


def _default_scene_entity(model: WorldModel, game_state: GameState | None) -> str:
    player = model.get_entity("Player")
    if player is not None:
        return player.key
    location_key = _default_scene_location(model, game_state)
    if location_key:
        actors = model.scene_snapshot(location_key).get("actors_here", [])
        for actor_key in actors:
            resolved = _resolve_entity_candidate(model, str(actor_key))
            if resolved:
                return resolved
    if model.entities:
        return sorted(model.entities.values(), key=lambda value: value.key.lower())[0].key
    return ""


def _default_scene_item(model: WorldModel, game_state: GameState | None) -> str:
    location_key = _default_scene_location(model, game_state)
    if location_key:
        scene_items = model.scene_snapshot(location_key).get("items_here", [])
        for item_key in scene_items:
            resolved = _resolve_item_candidate(model, str(item_key))
            if resolved:
                return resolved
    if model.items:
        return sorted(model.items.values(), key=lambda value: value.key.lower())[0].key
    return ""


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


def _get_turn_creation_counts(game_state: GameState) -> dict[str, int]:
    """Return the creation-count dict stored in the active turn context."""
    try:
        ctx = require_turn_orchestration_ctx(game_state)
        return ctx.setdefault("creation_counts", {"entities": 0, "items": 0})
    except Exception:
        return {"entities": 0, "items": 0}


def _slug(text: str) -> str:
    """Convert a display name to a safe key slug."""
    return _normalize_text(text).replace(" ", "_").replace("-", "_")


def _unique_key(model: WorldModel, base: str) -> str:
    """Return base if unused in the model, otherwise append an incrementing suffix."""
    if not model.has_key(base):
        return base
    suffix = 2
    while True:
        candidate = f"{base}_{suffix}"
        if not model.has_key(candidate):
            return candidate
        suffix += 1


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------

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
    location_key: str = "",
    world_model_data_dir: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    resolved_key = _resolve_location_candidate(model, location_key) or _default_scene_location(model, game_state)
    if not resolved_key:
        return {
            "success": True,
            "location": None,
            "reason": "No locations are available in the world model.",
        }
    location = model.get_location(resolved_key)
    if location is None:
        return {
            "success": False,
            "reason": f"Unknown location '{location_key}'.",
            "retryable": False,
        }
    return {
        "success": True,
        "location": location.to_record(),
        "resolved_location_key": resolved_key,
    }


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
    location_key: str = "",
    world_model_data_dir: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    resolved_key = _resolve_location_candidate(model, location_key) or _default_scene_location(model, game_state)
    if not resolved_key:
        return {"success": True, "scene": {"location": "", "description": "Unknown location", "connections": [], "actors_here": [], "items_here": []}}
    return {"success": True, "scene": model.scene_snapshot(resolved_key), "resolved_location_key": resolved_key}


def list_world_entities(
    entity_type: str = "",
    world_model_data_dir: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    return {"success": True, "entities": model.list_entity_records(entity_type=entity_type or None)}


def get_world_entity(
    entity_key: str = "",
    world_model_data_dir: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    resolved_key = _resolve_entity_candidate(model, entity_key) or _default_scene_entity(model, game_state)
    if not resolved_key:
        return {
            "success": True,
            "entity": None,
            "inventory": [],
            "reason": "No entities are available in the world model.",
        }
    entity = model.get_entity(resolved_key)
    if entity is None:
        return {
            "success": False,
            "reason": f"Unknown entity '{entity_key}'.",
            "retryable": False,
        }
    return {
        "success": True,
        "entity": entity.to_record(),
        "inventory": list(entity.inventory),
        "resolved_entity_key": resolved_key,
    }


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
    item_key: str = "",
    world_model_data_dir: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    resolved_key = _resolve_item_candidate(model, item_key) or _default_scene_item(model, game_state)
    if not resolved_key:
        return {
            "success": True,
            "item": None,
            "reason": "No items are available in the world model.",
        }
    item = model.get_item(resolved_key)
    if item is None:
        return {
            "success": False,
            "reason": f"Unknown item '{item_key}'.",
            "retryable": False,
        }
    return {
        "success": True,
        "item": item.to_record(),
        "resolved_item_key": resolved_key,
    }


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


# ---------------------------------------------------------------------------
# Runtime creation tools (Phase 2 only)
# ---------------------------------------------------------------------------

def create_npc(
    name: str,
    description: str = "",
    location: str = "",
    tags: list[str] | None = None,
    aliases: list[str] | None = None,
    memory_seeds: list[str] | None = None,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    """
    Create a new NPC in the world model when the player directly interacts
    with a character that has not been registered yet.
    """
    if game_state is None:
        return {"success": False, "reason": "Missing game_state context.", "retryable": False}

    clean_name = str(name or "").strip()
    if not clean_name:
        return {"success": False, "reason": "name is required.", "retryable": False}

    # Player identity protection
    if _normalize_text(clean_name) in _PROTECTED_KEYS:
        return {
            "success": False,
            "reason": "Cannot create an entity using a reserved name.",
            "retryable": False,
        }

    model = _load_model(world_model_data_dir, game_state=game_state)

    # Find before create - search the full world, not just the current scene.
    existing_key = _resolve_entity_candidate(model, clean_name)
    if existing_key:
        existing = model.get_entity(existing_key)
        # Register any new aliases on the already-existing entity so follow-up
        # references from the player also resolve.
        all_aliases = [clean_name] + (list(aliases) if aliases else [])
        register_entity_aliases(game_state, existing_key, all_aliases)
        return {
            "success": True,
            "created": False,
            "key": existing_key,
            "entity": existing.to_record() if existing else None,
            "reason": f"Entity matching '{clean_name}' already exists as '{existing_key}'.",
        }

    # Per-turn cap
    counts = _get_turn_creation_counts(game_state)
    if counts["entities"] >= MAX_ENTITY_CREATIONS_PER_TURN:
        return {
            "success": False,
            "reason": (
                f"Per-turn entity creation cap ({MAX_ENTITY_CREATIONS_PER_TURN}) reached. "
                "Cannot create more entities this turn."
            ),
            "retryable": False,
        }

    entity_key = _unique_key(model, _slug(clean_name))

    # Resolve location - default to the player's current location.
    resolved_location = ""
    if location:
        resolved_location = _resolve_location_candidate(model, location)
    if not resolved_location:
        resolved_location = _resolve_location_candidate(model, game_state.player_location)
    if not resolved_location:
        resolved_location = game_state.player_location
    if not resolved_location:
        resolved_location = model.starting_location

    payload: dict[str, Any] = {
        "key": entity_key,
        "name": clean_name,
        "entity_type": "npc",
        "description": str(description or "").strip(),
        "location": resolved_location,
        "skills": {},
        "stats": {},
        "tags": [str(t) for t in (tags or [])],
        "memory": [str(m) for m in (memory_seeds or [])],
    }
    entity = Entity.from_record(payload)
    model.add_entity(entity)
    model.sync_actor_inventories()

    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors, "retryable": False}

    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )

    counts["entities"] += 1

    all_aliases = [clean_name] + (list(aliases) if aliases else [])
    register_entity_aliases(game_state, entity_key, all_aliases)

    return {
        "success": True,
        "created": True,
        "key": entity_key,
        "entity": entity.to_record(),
        "save_path": save_path,
    }


def create_item(
    name: str,
    description: str = "",
    holder_kind: str = "location",
    holder_key: str = "",
    portable: bool = True,
    tags: list[str] | None = None,
    aliases: list[str] | None = None,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    """
    Create a new item in the world model when the player directly interacts
    with an object that has not been registered yet.
    """
    if game_state is None:
        return {"success": False, "reason": "Missing game_state context.", "retryable": False}

    clean_name = str(name or "").strip()
    if not clean_name:
        return {"success": False, "reason": "name is required.", "retryable": False}

    model = _load_model(world_model_data_dir, game_state=game_state)

    # Find before create
    existing_key = _resolve_item_candidate(model, clean_name)
    if existing_key:
        existing = model.get_item(existing_key)
        all_aliases = [clean_name] + (list(aliases) if aliases else [])
        register_entity_aliases(game_state, existing_key, all_aliases)
        return {
            "success": True,
            "created": False,
            "key": existing_key,
            "item": existing.to_record() if existing else None,
            "reason": f"Item matching '{clean_name}' already exists as '{existing_key}'.",
        }

    # Per-turn cap
    counts = _get_turn_creation_counts(game_state)
    if counts["items"] >= MAX_ITEM_CREATIONS_PER_TURN:
        return {
            "success": False,
            "reason": (
                f"Per-turn item creation cap ({MAX_ITEM_CREATIONS_PER_TURN}) reached. "
                "Cannot create more items this turn."
            ),
            "retryable": False,
        }

    item_key = _unique_key(model, _slug(clean_name))

    normalized_kind = str(holder_kind or "location").strip().lower()
    if normalized_kind not in {"location", "entity"}:
        normalized_kind = "location"

    resolved_holder_key = ""
    if holder_key:
        if normalized_kind == "location":
            resolved_holder_key = _resolve_location_candidate(model, holder_key)
        elif normalized_kind == "entity":
            resolved_holder_key = _resolve_entity_candidate(model, holder_key)

    if not resolved_holder_key:
        normalized_kind = "location"
        resolved_holder_key = _resolve_location_candidate(model, game_state.player_location)
    if not resolved_holder_key:
        resolved_holder_key = game_state.player_location
    if not resolved_holder_key:
        resolved_holder_key = model.starting_location

    item = Item.from_record(
        {
            "key": item_key,
            "name": clean_name,
            "description": str(description or "").strip(),
            "holder_kind": normalized_kind,
            "holder_key": resolved_holder_key,
            "portable": bool(portable),
            "tags": [str(t) for t in (tags or [])],
        }
    )
    model.add_item(item)
    model.sync_actor_inventories()

    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors, "retryable": False}

    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )

    counts["items"] += 1

    all_aliases = [clean_name] + (list(aliases) if aliases else [])
    register_entity_aliases(game_state, item_key, all_aliases)

    return {
        "success": True,
        "created": True,
        "key": item_key,
        "item": item.to_record(),
        "save_path": save_path,
    }


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

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
                "required": [],
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
                "required": [],
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
                "required": [],
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
                "required": [],
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
            "description": (
                "Move an existing item to a different location or entity holder. "
                "Use this in Phase 2 when a player picks up an item that was "
                "already in the world model."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_key": {"type": "string", "description": "Key of the item to move."},
                    "holder_kind": {"type": "string", "enum": ["location", "entity"], "description": "Whether the new holder is a location or an entity."},
                    "holder_key": {"type": "string", "description": "Key of the new holder."},
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
    {
        "type": "function",
        "function": {
            "name": "create_npc",
            "description": (
                "Create a new NPC in the world model when the player has directly "
                "interacted with a character not yet registered in the system. "
                "Uses find-or-create semantics: returns the existing key if a match "
                "is found rather than creating a duplicate. "
                "ONLY call this when the player explicitly addresses or acts on the "
                "character (talk to, push, examine up-close, attack, etc.). "
                "Do NOT call for flavor characters mentioned in narration who are "
                "never directly engaged. Do NOT create locations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Display name of the NPC (e.g. 'The Scarred Bartender').",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description drawn from narration context.",
                    },
                    "location": {
                        "type": "string",
                        "description": "Location key where the NPC appears. Defaults to the player's current location.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags such as 'bartender' or 'hostile'.",
                    },
                    "aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "All surface forms the narrator or player used for this character "
                            "before it was created (e.g. 'the man in the corner', 'scarred man'). "
                            "These are registered for future input resolution."
                        ),
                    },
                    "memory_seeds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional seed memories for the NPC drawn from narration.",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_item",
            "description": (
                "Create a new item in the world model when the player has directly "
                "interacted with an object not yet registered in the system. "
                "Uses find-or-create semantics: returns the existing key if a match "
                "is found rather than creating a duplicate. "
                "ONLY call this when the player explicitly addresses or acts on the "
                "object (examine, take, use, destroy, etc.). "
                "Do NOT call for scene-dressing objects the player ignores. "
                "If the player is taking the item, pass holder_kind='entity' and "
                "holder_key='Player' to place it in the player's inventory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Display name of the item (e.g. 'Bloodied Knife').",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description from narration context.",
                    },
                    "holder_kind": {
                        "type": "string",
                        "enum": ["location", "entity"],
                        "description": "Whether the item is at a location or held by an entity. Defaults to 'location'.",
                    },
                    "holder_key": {
                        "type": "string",
                        "description": "Key of the location or entity holding the item. Defaults to current player location.",
                    },
                    "portable": {
                        "type": "boolean",
                        "description": "Whether the item can be picked up. Defaults to true.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Surface forms used for this object before creation "
                            "(e.g. 'the painting', 'old portrait'). Registered for future resolution."
                        ),
                    },
                },
                "required": ["name"],
            },
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
    if tool_name == "create_npc":
        return create_npc(game_state=game_state, **arguments)
    if tool_name == "create_item":
        return create_item(game_state=game_state, **arguments)
    return {"success": False, "reason": f"Unknown world-model tool: {tool_name}"}


__all__ = [
    "MAX_ENTITY_CREATIONS_PER_TURN",
    "MAX_ITEM_CREATIONS_PER_TURN",
    "WORLD_MODEL_TOOL_DEFINITIONS",
    "create_item",
    "create_npc",
    "execute_world_model_tool",
    "get_world_entity",
    "get_world_item",
    "get_world_location",
    "get_world_scene",
    "get_world_story",
    "list_world_entities",
    "list_world_items",
    "list_world_locations",
    "move_world_entity",
    "move_world_item",
    "upsert_world_entity",
    "upsert_world_item",
    "upsert_world_location",
    "validate_world_model",
    "write_world_story",
]

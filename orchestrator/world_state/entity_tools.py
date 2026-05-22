from __future__ import annotations

from .story import GameState
from .tool_runtime import DynamicSentenceMemory, entity_public_view, find_world_object, get_runtime_world_model


def _is_in_current_scene(entity: object, game_state: GameState) -> bool:
    """
    Decide whether the resolved entity is considered "in the current scene".

    Used by retrieve_memory_tool to redirect the caller back to check_can_interact for in-scene targets. The rule:
    - Locations: the entity counts as in-scene if it is the current location.
    - NPCs/Items: in-scene if their location equals the player's, or carried by an NPC at the player's location.
    Anything else (off-scene NPC, distant location, item in a far warehouse) is out-of-scene and retrieve_memory_tool should answer it normally.
    """
    if entity is None or game_state is None:
        return False
    try:
        player_loc = str(game_state.player_location or "").strip()
    except Exception:
        return False
    if not player_loc:
        return False

    entity_type = str(getattr(entity, "entity_type", "") or "").lower()

    # Locations.
    if entity_type == "location":
        return getattr(entity, "key", "") == player_loc

    # Actors / NPCs / the Player.
    if entity_type in ("npc", "player", "character", "monster"):
        return str(getattr(entity, "location", "") or "") == player_loc

    # Items.
    if entity_type == "item":
        holder_kind = str(getattr(entity, "holder_kind", "") or "").lower()
        holder_key = str(getattr(entity, "holder_key", "") or "")
        if holder_kind == "location" and holder_key == player_loc:
            return True
        if holder_kind == "entity":
            try:
                model = get_runtime_world_model(game_state)
                holder = model.get_entity(holder_key) if model else None
            except Exception:
                holder = None
            if holder is not None and str(getattr(holder, "location", "") or "") == player_loc:
                return True
        return False

    # Fallback: treat anything with a location field that matches as in-scene.
    location_field = getattr(entity, "location", None)
    if isinstance(location_field, str) and location_field == player_loc:
        return True
    return False


def get_entity_state(
    entity_key: str = "Player",
    include_memory_preview: bool = False,
    memory_preview: int = 3,
    game_state: GameState | None = None,
) -> dict[str, object]:
    if game_state is None:
        return {
            "success": False,
            "reason": "Missing game_state context.",
            "retryable": False,
        }

    resolved_entity = str(entity_key or "").strip() or "Player"
    entity = find_world_object(resolved_entity, game_state)
    if entity is None:
        return {
            "success": False,
            "reason": f"World object '{entity_key}' not found.",
            "retryable": False,
        }

    return {
        "success": True,
        "entity": entity_public_view(
            entity,
            include_memory_preview=bool(include_memory_preview),
            memory_preview=max(0, int(memory_preview)),
        ),
    }


def retrieve_memory_tool(
    entity_name: str = "Player",
    context: str = "",
    top_n: int = 4,
    game_state: GameState | None = None,
) -> dict[str, object]:
    """
    Look up the memory of a world object that is NOT in the current scene.

    For any entity, item, or location the player can currently interact with,
    check_can_interact already surfaces a recent-memory preview to the narrator.
    Don't need to call this tool for those targets.
    
    This tool exists for the off-scene case: the player asks about a distant character,
    or an item the player remembers from another location, or a place they have been to before.

    If the resolved target is in the current scene, this tool refuses with a
    redirect message so the model learns to use check_can_interact instead.
    """
    if game_state is None:
        return {
            "success": False,
            "message": "Missing game_state context.",
            "memories": [],
            "retryable": False,
        }

    resolved_entity = str(entity_name or "").strip() or "Player"
    entity = find_world_object(resolved_entity, game_state)
    if entity is None:
        return {
            "success": False,
            "message": f"World object '{resolved_entity}' is not registered.",
            "memories": [],
            "retryable": False,
        }

    # In-scene targets get their memory through check_can_interact.
    # Refuse with a redirect so the model uses the right tool.
    # Returning success=False with retryable=False keeps this from triggering retry loops.
    if _is_in_current_scene(entity, game_state):
        entity_type = str(getattr(entity, "entity_type", "") or "").lower() or "world object"
        return {
            "success": False,
            "message": (
                f"'{entity.name}' is in the current scene. retrieve_memory_tool "
                f"is for off-scene lookups only; check_can_interact already "
                f"surfaces this {entity_type}'s recent memory to the narrator. "
                f"Do not retry."
            ),
            "memories": [],
            "retryable": False,
            "entity_key": entity.key,
            "entity_name": entity.name,
            "redirect": "check_can_interact",
        }

    query = str(context or "").strip()
    if not query:
        return {
            "success": True,
            "entity_key": entity.key,
            "entity_name": entity.name,
            "entity_type": str(getattr(entity, "entity_type", "") or ""),
            "memory_backend": DynamicSentenceMemory.backend_status(),
            "memories": [],
            "message": "No context provided for memory retrieval.",
        }

    hits = entity.search_memory(query, top_n=max(1, int(top_n)))
    return {
        "success": True,
        "entity_key": entity.key,
        "entity_name": entity.name,
        "entity_type": str(getattr(entity, "entity_type", "") or ""),
        "memory_backend": DynamicSentenceMemory.backend_status(),
        "memories": [{"sentence": hit.sentence, "score": float(hit.score)} for hit in hits],
    }


def write_memory_tool(
    entity_name: str = "Player",
    memory: str = "",
    relevance: float = 100.0,
    context: str = "",
    game_state: GameState | None = None,
) -> dict[str, object]:
    if game_state is None:
        return {
            "success": False,
            "message": "Missing game_state context.",
            "retryable": False,
        }

    resolved_entity = str(entity_name or "").strip() or "Player"
    entity = find_world_object(resolved_entity, game_state)
    if entity is None:
        return {
            "success": False,
            "message": f"World object '{resolved_entity}' is not registered.",
            "retryable": False,
        }

    text = str(memory or context or "").strip()
    if not text:
        return {
            "success": True,
            "entity_name": entity.name,
            "message": "No memory text provided; skipped write.",
            "memory_count": entity.memory_count,
        }

    entity.add_memory(text)
    return {
        "success": True,
        "entity_name": entity.name,
        "memory": text,
        "relevance": float(relevance),
        "memory_count": entity.memory_count,
    }


ENTITY_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_entity_state",
            "description": "Read detailed state variables for a world object (location, actor, or item).",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_key": {"type": "string", "description": "World object key or name."},
                    "include_memory_preview": {"type": "boolean"},
                    "memory_preview": {"type": "integer", "minimum": 0, "maximum": 20},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_memory_tool",
            "description": (
                "Look up the memory of a world object that is NOT in the current scene." 
                "Use this only when the player references a distant character, item, or location they are not currently interacting with." 
                "For example, the player asks about a character who is not in the room, or recalls events at a place they left earlier."
                "Do NOT call this for entities in the current scene because check_can_interact already surfaces their recent memory to the narrator."
                "Calling this for an in-scene target returns a redirect."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {"type": "string", "description": "World object name or key (must not be in the current scene)."},
                    "context": {"type": "string", "description": "Query context for similarity search."},
                    "top_n": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_memory_tool",
            "description": "Write a new memory sentence into a world object's memory store.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {"type": "string", "description": "World object name or key."},
                    "memory": {"type": "string", "description": "Sentence or fact to store."},
                    "context": {"type": "string", "description": "Alias for memory (notebook compatibility)."},
                    "relevance": {"type": "number", "minimum": 0, "maximum": 1000},
                },
                "required": [],
            },
        },
    },
]


__all__ = [
    "ENTITY_TOOL_DEFINITIONS",
    "get_entity_state",
    "retrieve_memory_tool",
    "write_memory_tool",
]

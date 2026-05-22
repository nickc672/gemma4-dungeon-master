from __future__ import annotations

from typing import Any, Optional

from .mechanics_tools import skill_check as run_skill_check
from .story import GameState, mark_location_visited
from .tool_runtime import (
    ensure_entity_registry,
    find_route_via_visited,
    get_runtime_world_model,
    normalize_key,
    register_entity_aliases,
    require_turn_orchestration_ctx,
    resolve_alias,
)


HISTORY_CHECK_BASE_DC = 5
HISTORY_CHECK_DC_PER_HOP = 3
CHECK_CAN_INTERACT_MEMORY_PREVIEW_COUNT = 10 # Number of stored memory sentences attached to a successful check_can_interact result.


def _memory_preview_lines(entity: Any, limit: int = CHECK_CAN_INTERACT_MEMORY_PREVIEW_COUNT) -> list[str]:
    """Return up to the limit of trailing memory sentences for an entity, oldest-first."""
    if entity is None:
        return []
    raw = list(getattr(getattr(entity, "memory", None), "sentences", []) or [])
    cleaned = [str(line).strip() for line in raw if str(line).strip()]
    if not cleaned:
        return []
    if limit and limit > 0:
        cleaned = cleaned[-int(limit):]
    return cleaned


def _augment_success_with_memory(result: dict, entity: Any) -> dict:
    """
    Attach the resolved entity's identity and a short memory preview to a successful check_can_interact result.
    The memory preview is what feeds the narration prompt. 
    The entity_key and entity_name fields let the narration prompt builder deduplicate memories across multiple Phase 1 lookups.
    """
    if entity is None:
        return result
    result["entity_key"] = entity.key
    result["entity_name"] = entity.name
    result["entity_memory"] = _memory_preview_lines(entity)
    return result


def _request_manual_history_roll(game_state: GameState, dc: int, context: str) -> int | None:
    try:
        ctx = require_turn_orchestration_ctx(game_state)
    except Exception:
        return None
    mode = str(ctx.get("roll_mode") or "").strip().lower()
    provider = ctx.get("manual_roll_provider")
    if mode != "manual" or not callable(provider):
        return None
    request = {
        "tool_name": "skill_check",
        "phase": str(ctx.get("phase") or "phase_one"),
        "arguments": {
            "entity_key": "Player",
            "skill": "history",
            "dc": int(dc),
            "context": str(context or ""),
        },
    }
    try:
        value = int(provider(request))
    except Exception:
        return None
    if value < 1 or value > 20:
        return None
    return value


def _resolve_target_key(model: Any, raw_key: str, game_state: Optional[GameState] = None) -> str:
    candidate = str(raw_key or "").strip()
    if not candidate:
        return ""

    # Check alias registry before anything else so new objects
    # resolve immediately without relying on fuzzy matching.
    if game_state is not None:
        alias_key = resolve_alias(game_state, candidate)
        if alias_key is not None:
            obj = model.get_object(alias_key)
            if obj is not None:
                return obj.key

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


def _history_check_dc(path: list[str]) -> int:
    intermediate_count = max(0, len(path) - 2)
    return HISTORY_CHECK_BASE_DC + HISTORY_CHECK_DC_PER_HOP * intermediate_count


def check_can_interact(entity_key: str = "", game_state: GameState | None = None) -> dict[str, object]:
    if game_state is None:
        return {"success": False, "can_interact": False, "reason": "Missing game_state context."}
    model = get_runtime_world_model(game_state)
    player_loc = game_state.player_location

    raw_target = str(entity_key or "").strip()
    resolved_key = _resolve_target_key(model, raw_target, game_state)

    # Target was specified but could not be resolved to any existing world object.
    # Record it as an unresolved interaction target so Phase 2 can decide whether
    # to materialize it if the narration describes a real directed interaction.
    if raw_target and not resolved_key:
        try:
            ctx = require_turn_orchestration_ctx(game_state)
            targets = ctx.setdefault("unresolved_interaction_targets", [])
            if raw_target not in targets:
                targets.append(raw_target)
        except Exception:
            pass
        return {
            "success": True,
            "can_interact": False,
            "reason": f"'{raw_target}' does not exist in the world model.",
            "nearby": model.scene_snapshot(player_loc),
            "unresolved_target": raw_target,
        }

    if not resolved_key:
        resolved_key = player_loc
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
            return _augment_success_with_memory({
                "success": True,
                "can_interact": True,
                "entity_type": location.type,
                "reason": "You are already at this location.",
                "path": [player_loc],
            }, location)
        if location.key in current_location.connections:
            return _augment_success_with_memory({
                "success": True,
                "can_interact": True,
                "entity_type": location.type,
                "reason": f"{location.key} is directly adjacent to {player_loc}.",
                "path": [player_loc, location.key],
            }, location)

        # Non-adjacent. If the destination itself has been visited before,
        # the player already knows the way, no History check needed. We
        # still need a route to actually walk back, but the route only has
        # to exist
        if location.key in game_state.visited_locations:
            route = find_route_via_visited(
                model,
                player_loc,
                location.key,
                game_state.visited_locations,
            )
            if route is not None and len(route) >= 2:
                return _augment_success_with_memory({
                    "success": True,
                    "can_interact": True,
                    "entity_type": location.type,
                    "reason": (
                        f"{location.key} is not adjacent but has been visited "
                        f"before; the player remembers the route via "
                        f"{' -> '.join(route)}. No History check required."
                    ),
                    "path": list(route),
                }, location)
            # unlikely, but if destination is in visited_locations but no path
            # through visited intermediates connects it.
            return {
                "success": True,
                "can_interact": False,
                "entity_type": location.type,
                "reason": (
                    f"{location.key} has been visited before but no current "
                    "path through visited locations connects it to "
                    f"{player_loc}. The route may have been altered."
                ),
            }

        # Destination is non-adjacent and not previously visited. Look for
        # a route whose intermediate steps are all visited locations.
        route = find_route_via_visited(
            model,
            player_loc,
            location.key,
            game_state.visited_locations,
        )
        if route is None or len(route) < 3:
            return {
                "success": True,
                "can_interact": False,
                "entity_type": location.type,
                "reason": (
                    f"{location.key} is not reachable from {player_loc} via any "
                    "known route. The player would need to travel through "
                    "unfamiliar territory to get there."
                ),
            }

        # A route exists. Roll a History check to see if the player
        # remembers the way.
        dc = _history_check_dc(route)
        roll_context = f"Recall the route from {player_loc} to {location.key}."
        manual_value = _request_manual_history_roll(game_state, dc, roll_context)
        check_kwargs: dict[str, object] = {
            "entity_key": "Player",
            "skill": "history",
            "dc": dc,
            "context": roll_context,
            "game_state": game_state,
        }
        if manual_value is not None:
            check_kwargs["_manual_roll"] = manual_value
        history_check = run_skill_check(**check_kwargs)  # type: ignore[arg-type]
        history_summary = {
            "dc": dc,
            "total": history_check.get("total"),
            "passed": history_check.get("success"),
            "route": list(route),
        }
        check_entry = next(
            (
                entry for entry in reversed(history_check.get("log", []))
                if entry.get("skill") == "history"
            ),
            history_check,
        )
        if history_check.get("success"):
            roll_total = check_entry.get("total")
            return _augment_success_with_memory({
                "success": True,
                "can_interact": True,
                "entity_type": location.type,
                "reason": (
                    f"[History DC {dc} passed, total {roll_total}] "
                    f"{location.key} is reachable via "
                    f"{' -> '.join(route)}; the player recalls the way."
                ),
                "path": list(route),
                "history_check": history_summary,
            }, location)
        roll_total = check_entry.get("total")
        return {
            "success": True,
            "can_interact": False,
            "entity_type": location.type,
            "reason": (
                f"[History DC {dc} failed, total {roll_total}] "
                f"{location.key} is not directly adjacent. The player "
                f"tried to recall the route via {' -> '.join(route)} but "
                "could not remember the way."
            ),
            "path": list(route),
            "history_check": history_summary,
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
            return _augment_success_with_memory({
                "success": True,
                "can_interact": True,
                "entity_type": entity.entity_type,
                "reason": f"{entity.key} is here.",
            }, entity)
        return {
            "success": True,
            "can_interact": False,
            "entity_type": entity.entity_type,
            "reason": f"{entity.key} is at {entity.location}.",
        }

    item = model.get_item(entity_key)
    if item is not None:
        if item.is_at_location(player_loc):
            return _augment_success_with_memory({
                "success": True,
                "can_interact": True,
                "entity_type": item.type,
                "reason": f"{item.key} is here.",
            }, item)
        if item.holder_kind == "entity":
            holder = model.get_entity(item.holder_key)
            if holder is not None and holder.location == player_loc:
                return _augment_success_with_memory({
                    "success": True,
                    "can_interact": True,
                    "entity_type": item.type,
                    "reason": f"{item.key} is being carried by {holder.key}.",
                }, item)
        return {
            "success": True,
            "can_interact": False,
            "entity_type": item.type,
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
        return {
            "success": False,
            "new_location": None,
            "reason": "Missing game_state context.",
            "retryable": False,
        }
    model = get_runtime_world_model(game_state)
    if not str(location_key or "").strip():
        return {
            "success": True,
            "new_location": game_state.player_location,
            "reason": "No destination provided. Staying at current location.",
        }
    resolved_destination = _resolve_target_key(model, location_key, game_state)
    if resolved_destination and model.get_location(resolved_destination) is not None:
        location_key = resolved_destination
    location = model.get_location(location_key)
    if location is None:
        return {
            "success": False,
            "new_location": None,
            "reason": f"Location '{location_key}' does not exist.",
            "retryable": False,
        }

    current_location = model.get_location(game_state.player_location)
    if current_location is None:
        return {
            "success": False,
            "new_location": None,
            "reason": "Invalid current location.",
            "retryable": False,
        }
    if location_key == game_state.player_location:
        return {
            "success": True,
            "new_location": location_key,
            "reason": "You are already here.",
            "path": [location_key],
        }

    # Find a route. Direct neighbor returns a 2-step path
    route = find_route_via_visited(
        model,
        game_state.player_location,
        location.key,
        game_state.visited_locations,
    )
    if route is None or len(route) < 2:
        return {
            "success": False,
            "new_location": None,
            "reason": (
                f"Cannot move to {location.key}. No route exists from "
                f"{game_state.player_location} through visited locations."
            ),
            "retryable": False,
        }

    # Auto-route: walk the path one hop at a time. Every step must be a
    # real connection in the world graph; we mark each location visited
    # as we arrive there.
    traversed: list[str] = [game_state.player_location]
    for hop_index in range(1, len(route)):
        prev_key = route[hop_index - 1]
        next_key = route[hop_index]
        prev_location = model.get_location(prev_key)
        if prev_location is None or next_key not in prev_location.connections:
            return {
                "success": False,
                "new_location": None,
                "reason": (
                    f"Auto-route broke at {prev_key} to {next_key}: that "
                    "connection does not exist in the world graph."
                ),
                "path_attempted": list(route),
                "path_traversed": traversed,
                "retryable": False,
            }
        if not model.move_entity("Player", next_key):
            return {
                "success": False,
                "new_location": None,
                "reason": "Player entity is missing from the world model.",
                "path_attempted": list(route),
                "path_traversed": traversed,
                "retryable": False,
            }
        game_state.player_location = next_key
        mark_location_visited(game_state, next_key, model)
        traversed.append(next_key)

    if len(traversed) > 2:
        reason = (
            f"Auto-routed to {location.key} via "
            f"{' -> '.join(traversed)} ({len(traversed) - 1} hops)."
        )
    else:
        reason = f"Moved to {location.key}."

    return {
        "success": True,
        "new_location": location.key,
        "reason": reason,
        "path": traversed,
    }


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
        "visited_locations": sorted(game_state.visited_locations),
        "discovered_locations": sorted(game_state.discovered_locations),
    }


def move_npc(npc_key: str = "", new_location: str = "", game_state: GameState | None = None) -> dict[str, object]:
    if game_state is None:
        return {
            "success": False,
            "reason": "Missing game_state context.",
            "retryable": False,
        }
    model = get_runtime_world_model(game_state)
    if not str(npc_key or "").strip() or not str(new_location or "").strip():
        return {"success": True, "reason": "Missing npc_key or new_location. No NPC movement applied."}
    resolved_npc = _resolve_target_key(model, npc_key, game_state)
    resolved_location = _resolve_target_key(model, new_location, game_state)
    npc = model.get_entity(resolved_npc or npc_key)
    if npc is None:
        return { 
            "success": False,
            "reason": f"NPC '{npc_key}' does not exist.",
            "retryable": False,
        }
    if npc.entity_type != "npc":
        return {
            "success": False,
            "reason": f"'{npc_key}' is not an NPC.",
            "retryable": False,
        }
    location = model.get_location(resolved_location or new_location)
    if location is None:
        return {
            "success": False,
            "reason": f"Location '{new_location}' does not exist.",
            "retryable": False,
        }

    # Capture the source location before the move so we can write a departure memory on it.
    source_location_key = str(getattr(npc, "location", "") or "").strip()
    source_location = (
        model.get_location(source_location_key) if source_location_key else None
    )

    # No-op if the NPC is already at the destination.
    if source_location is not None and source_location.key == location.key:
        return {
            "success": True,
            "reason": f"{npc.key} is already at {location.key}; no movement applied.",
        }

    model.move_entity(npc.key, location.key)
    game_state.npc_locations[npc.key] = location.key

    # Auto-write departure and arrival memories so location memory carries
    # the narrative thread of NPC movement. Both lines embed "key: <npc_key>"
    # so the location-memory linker recognises them as already linked and
    # never tries to wrap the canonical name with a duplicate marker.
    memory_writes: dict[str, str] = {}
    npc_name = str(getattr(npc, "name", "") or npc.key).strip() or npc.key
    npc_marker = f"key: {npc.key}"

    if source_location is not None and source_location.key != location.key:
        destination_label = str(location.name or location.key).strip() or location.key
        departure_line = (
            f"{npc_name} ({npc_marker}) left toward {destination_label}."
        )
        if departure_line not in source_location.memory.sentences:
            source_location.memory.add_memory(departure_line)
            memory_writes[source_location.key] = departure_line

    origin_label = ""
    if source_location is not None:
        origin_label = str(source_location.name or source_location.key).strip() or source_location.key

    if origin_label:
        arrival_line = (
            f"{npc_name} ({npc_marker}) arrived from {origin_label}."
        )
    else:
        # NPC had no prior location (just created, or unknown origin).
        arrival_line = f"{npc_name} ({npc_marker}) appeared here."

    if arrival_line not in location.memory.sentences:
        location.memory.add_memory(arrival_line)
        memory_writes[location.key] = arrival_line

    return {
        "success": True,
        "reason": f"{npc.key} moved to {location.key}.",
        "memory_writes": memory_writes,
    }


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
                "entity_type": location.type,
                "location": location.key,
                "memory_count": location.memory_count,
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
                "entity_type": item.type,
                "location": scene.get("location"),
                "memory_count": item.memory_count,
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
            "description": (
                "This tool is used for checking if the player can interact with"
                "any person, place, or thing. This tool is likely used every turn."
                "Check if the player can interact with an entity or travel to a "
                "location. For locations: returns can_interact=True if the target "
                "is the current location or directly adjacent. For non-adjacent "
                "locations, this tool searches for a route through visited "
                "locations and rolls a History check (DC 5 + 2 per intermediate "
                "hop) to see if the player remembers the way. Use this before "
                "narrating any movement or interaction. If the target does not "
                "exist in the world model, the result will include unresolved_target "
                "so Phase 2 can create it if the narration describes a real interaction. "
                "On any successful check (can_interact=True), the target's recent "
                "memory is automatically attached to the result and forwarded to "
                "the narrator; no separate retrieve_memory_tool call is needed for "
                "entities, items, or locations confirmed reachable by this tool."
            ),
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
            "description": (
                "Move the player to a destination. Direct adjacency moves in a "
                "single step. Non-adjacent destinations auto-route through "
                "visited locations when a path exists; the player walks each "
                "hop and every traversed location is marked visited. Fails if "
                "no route through visited locations reaches the destination."
            ),
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
    "CHECK_CAN_INTERACT_MEMORY_PREVIEW_COUNT",
    "HISTORY_CHECK_BASE_DC",
    "HISTORY_CHECK_DC_PER_HOP",
    "SCENE_TOOL_DEFINITIONS",
    "VALIDATE_TOOLS",
    "check_can_interact",
    "get_current_context",
    "list_scene_entities",
    "move_npc",
    "move_to_location",
]

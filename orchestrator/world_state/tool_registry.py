from __future__ import annotations

import inspect
from typing import Any, Callable, Dict

from .entity_tools import ENTITY_TOOL_DEFINITIONS, get_entity_state, retrieve_memory_tool, write_memory_tool
from .mechanics_tools import MECHANICS_TOOL_DEFINITIONS, get_recent_skill_checks, roll_dice, skill_check
from .scene_tools import (
    SCENE_TOOL_DEFINITIONS,
    VALIDATE_TOOLS,
    check_can_interact,
    get_current_context,
    list_scene_entities,
    move_npc,
    move_to_location,
)
from .story import GameState
from .turn_tools import (
    FINALIZE_TURN_TOOL_DEFINITION,
    TURN_TODO_TOOL_DEFINITIONS,
    add_turn_note,
    finalize_turn,
    get_turn_progress,
    get_turn_todo,
    set_todo_item_status,
    set_turn_todo,
)
from .world_model_tools import (
    WORLD_MODEL_TOOL_DEFINITIONS,
    execute_world_model_tool,
    get_world_entity,
    get_world_item,
    get_world_location,
    get_world_scene,
    get_world_story,
    list_world_entities,
    list_world_items,
    list_world_locations,
)


RuntimeToolHandler = Callable[..., dict[str, Any]]

RUNTIME_TOOL_HANDLERS: Dict[str, RuntimeToolHandler] = {
    "set_turn_todo": set_turn_todo,
    "get_turn_todo": get_turn_todo,
    "set_todo_item_status": set_todo_item_status,
    "get_turn_progress": get_turn_progress,
    "add_turn_note": add_turn_note,
    "finalize_turn": finalize_turn,
    "check_can_interact": check_can_interact,
    "get_current_context": get_current_context,
    "move_to_location": move_to_location,
    "move_npc": move_npc,
    "list_scene_entities": list_scene_entities,
    "get_entity_state": get_entity_state,
    "retrieve_memory_tool": retrieve_memory_tool,
    "write_memory_tool": write_memory_tool,
    "roll_dice": roll_dice,
    "skill_check": skill_check,
    "get_recent_skill_checks": get_recent_skill_checks,
    "get_world_story": get_world_story,
    "list_world_locations": list_world_locations,
    "get_world_location": get_world_location,
    "get_world_scene": get_world_scene,
    "list_world_entities": list_world_entities,
    "get_world_entity": get_world_entity,
    "list_world_items": list_world_items,
    "get_world_item": get_world_item,
}

WORLD_MODEL_READ_TOOL_NAMES = (
    "get_world_story",
    "list_world_locations",
    "get_world_location",
    "get_world_scene",
    "list_world_entities",
    "get_world_entity",
    "list_world_items",
    "get_world_item",
)

WORLD_MODEL_READ_TOOL_DEFINITIONS = [
    tool
    for tool in WORLD_MODEL_TOOL_DEFINITIONS
    if tool.get("function", {}).get("name") in WORLD_MODEL_READ_TOOL_NAMES
]

TOOL_DEFINITION_GROUPS = {
    "turn": TURN_TODO_TOOL_DEFINITIONS,
    "validate": VALIDATE_TOOLS,
    "scene": SCENE_TOOL_DEFINITIONS,
    "entity": ENTITY_TOOL_DEFINITIONS,
    "mechanics": MECHANICS_TOOL_DEFINITIONS,
    "world": WORLD_MODEL_READ_TOOL_DEFINITIONS,
    "finalize": [FINALIZE_TURN_TOOL_DEFINITION],
}

TOOL_NAMES_BY_GROUP = {
    group_name: tuple(tool["function"]["name"] for tool in definitions)
    for group_name, definitions in TOOL_DEFINITION_GROUPS.items()
}

RUNTIME_TOOL_NAMES = tuple(RUNTIME_TOOL_HANDLERS.keys())
WORLD_MODEL_TOOL_NAMES = tuple(tool["function"]["name"] for tool in WORLD_MODEL_TOOL_DEFINITIONS)

TOOL_DEFINITIONS = [
    *TOOL_DEFINITION_GROUPS["validate"],
    *TOOL_DEFINITION_GROUPS["scene"],
    *TOOL_DEFINITION_GROUPS["entity"],
    *TOOL_DEFINITION_GROUPS["mechanics"],
    *TOOL_DEFINITION_GROUPS["world"],
]


def get_tool_names(*, include_turn: bool = False, include_world_model: bool = False) -> tuple[str, ...]:
    names = list(RUNTIME_TOOL_NAMES)
    if not include_turn:
        turn_names = set(TOOL_NAMES_BY_GROUP["turn"])
        names = [name for name in names if name not in turn_names]
    if include_world_model:
        names.extend(name for name in WORLD_MODEL_TOOL_NAMES if name not in names)
    return tuple(names)


def _first_present(arguments: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in arguments:
            value = arguments.get(key)
            if isinstance(value, str):
                if value.strip():
                    return value.strip()
                continue
            if value is not None:
                return value
    return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _normalize_tool_arguments(
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    args = dict(arguments or {})
    if not isinstance(args, dict):
        return {}

    if tool_name in {"get_world_scene", "get_world_location", "move_to_location", "move_world_entity"}:
        location_key = _first_present(
            args,
            "location_key",
            "location",
            "destination",
            "target_location",
            "target",
            "new_location",
        )
        if location_key is not None:
            args["location_key"] = str(location_key).strip()

    if tool_name in {"check_can_interact"}:
        entity_key = _first_present(
            args,
            "entity_key",
            "entity",
            "entity_name",
            "target",
            "name",
            "npc_key",
            "item_key",
            "location_key",
        )
        if entity_key is not None:
            args["entity_key"] = str(entity_key).strip()

    if tool_name in {"get_world_entity", "get_entity_state", "move_world_entity"}:
        entity_key = _first_present(
            args,
            "entity_key",
            "entity",
            "entity_name",
            "target",
            "name",
            "npc_key",
        )
        if entity_key is not None:
            args["entity_key"] = str(entity_key).strip()

    if tool_name in {"get_world_item", "move_world_item"}:
        item_key = _first_present(args, "item_key", "item", "item_name", "target", "name")
        if item_key is not None:
            args["item_key"] = str(item_key).strip()

    if tool_name in {"retrieve_memory_tool", "write_memory_tool"}:
        entity_name = _first_present(args, "entity_name", "entity_key", "entity", "target", "name")
        if entity_name is not None:
            args["entity_name"] = str(entity_name).strip()
        context = _first_present(args, "context", "query", "memory", "text", "note", "details")
        if context is not None and not str(args.get("context", "")).strip():
            args["context"] = str(context).strip()
        if tool_name == "write_memory_tool":
            memory = _first_present(args, "memory", "text", "note", "context")
            if memory is not None:
                args["memory"] = str(memory).strip()

    if tool_name == "skill_check":
        entity_key = _first_present(args, "entity_key", "entity", "entity_name", "target", "name")
        if entity_key is not None:
            args["entity_key"] = str(entity_key).strip()
        skill = _first_present(args, "skill", "skill_name", "check", "ability", "stat")
        if skill is not None:
            args["skill"] = str(skill).strip()
        dc = _first_present(args, "dc", "difficulty", "difficulty_class", "target_dc")
        dc_int = _to_int(dc)
        if dc_int is not None:
            args["dc"] = dc_int

    if tool_name == "roll_dice":
        for canonical, aliases in {
            "sides": ("sides", "die_sides", "faces"),
            "count": ("count", "num_dice", "dice_count"),
            "modifier": ("modifier", "mod", "bonus"),
        }.items():
            value = _first_present(args, *aliases)
            casted = _to_int(value)
            if casted is not None:
                args[canonical] = casted

    if tool_name == "list_world_entities":
        entity_type = _first_present(args, "entity_type", "type", "kind")
        if entity_type is not None:
            args["entity_type"] = str(entity_type).strip()

    if tool_name == "list_world_items":
        holder_kind = _first_present(args, "holder_kind", "kind", "type")
        holder_key = _first_present(args, "holder_key", "holder", "owner", "entity_key", "location_key")
        if holder_kind is not None:
            args["holder_kind"] = str(holder_kind).strip()
        if holder_key is not None:
            args["holder_key"] = str(holder_key).strip()

    if tool_name == "move_world_item":
        holder_kind = _first_present(args, "holder_kind", "kind", "target_kind")
        holder_key = _first_present(args, "holder_key", "holder", "owner", "entity_key", "location_key", "location")
        if holder_kind is not None:
            args["holder_kind"] = str(holder_kind).strip()
        if holder_key is not None:
            args["holder_key"] = str(holder_key).strip()

    if tool_name == "move_npc":
        npc_key = _first_present(args, "npc_key", "entity_key", "entity", "npc", "name", "target")
        new_location = _first_present(args, "new_location", "location_key", "location", "destination", "target_location")
        if npc_key is not None:
            args["npc_key"] = str(npc_key).strip()
        if new_location is not None:
            args["new_location"] = str(new_location).strip()

    return args


def _call_handler(handler: RuntimeToolHandler, arguments: dict[str, Any], game_state: GameState) -> dict[str, Any]:
    signature = inspect.signature(handler)
    accepted = {
        name for name in signature.parameters
        if name != "game_state"
    }
    filtered_arguments = {
        key: value for key, value in arguments.items()
        if key in accepted
    }
    return handler(game_state=game_state, **filtered_arguments)


def execute_tool(tool_name: str, arguments: dict[str, Any], game_state: GameState) -> dict[str, Any]:
    handler = RUNTIME_TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return {"success": False, "reason": f"Unknown tool: {tool_name}"}
    normalized_arguments = _normalize_tool_arguments(tool_name, arguments)
    try:
        return _call_handler(handler, normalized_arguments, game_state)
    except TypeError:
        try:
            return _call_handler(handler, {}, game_state)
        except TypeError as exc:
            return {"success": False, "reason": f"Invalid arguments for {tool_name}: {exc}"}


__all__ = [
    "RUNTIME_TOOL_HANDLERS",
    "RUNTIME_TOOL_NAMES",
    "TOOL_DEFINITION_GROUPS",
    "TOOL_DEFINITIONS",
    "TOOL_NAMES_BY_GROUP",
    "TURN_TODO_TOOL_DEFINITIONS",
    "VALIDATE_TOOLS",
    "WORLD_MODEL_TOOL_DEFINITIONS",
    "WORLD_MODEL_READ_TOOL_DEFINITIONS",
    "WORLD_MODEL_READ_TOOL_NAMES",
    "WORLD_MODEL_TOOL_NAMES",
    "execute_tool",
    "execute_world_model_tool",
    "get_tool_names",
]

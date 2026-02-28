from __future__ import annotations

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
    TURN_TODO_TOOL_DEFINITIONS,
    add_turn_note,
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


def execute_tool(tool_name: str, arguments: dict[str, Any], game_state: GameState) -> dict[str, Any]:
    handler = RUNTIME_TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return {"success": False, "reason": f"Unknown tool: {tool_name}"}
    return handler(game_state=game_state, **arguments)


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

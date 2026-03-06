from __future__ import annotations

import random
from typing import Any

from .story import GameState
from .tool_runtime import SKILL_TO_STAT, find_entity, normalize_key, skill_check_log


def roll_dice(
    sides: int = 20,
    count: int = 1,
    modifier: int = 0,
    label: str = "",
    _manual_roll: int | None = None,
    game_state: GameState | None = None,
) -> dict[str, object]:
    _ = game_state
    sides = int(sides)
    count = int(count)
    modifier = int(modifier)

    if sides < 2 or sides > 1000:
        return {"success": False, "reason": "sides must be between 2 and 1000."}
    if count < 1 or count > 20:
        return {"success": False, "reason": "count must be between 1 and 20."}

    if _manual_roll is not None:
        if count != 1:
            return {"success": False, "reason": "manual roll override only supports single-die rolls."}
        roll_value = int(_manual_roll)
        if roll_value < 1 or roll_value > sides:
            return {"success": False, "reason": f"manual roll must be between 1 and {sides}."}
        rolls = [roll_value]
    else:
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
    entity_key: str = "Player",
    skill: str = "perception",
    dc: int = 10,
    context: str = "",
    top_memory: int = 0,
    _manual_roll: int | None = None,
    game_state: GameState | None = None,
) -> dict[str, object]:
    if game_state is None:
        return {"success": False, "reason": "Missing game_state context."}

    resolved_entity = str(entity_key or "").strip() or "Player"
    entity = find_entity(resolved_entity, game_state)
    if entity is None:
        entity = find_entity("Player", game_state)
    if entity is None:
        return {"success": False, "reason": f"Entity '{entity_key}' not found."}

    skill_key = normalize_key(skill or "perception").replace(" ", "_") or "perception"
    try:
        target_dc = int(dc)
    except Exception:
        target_dc = 10
    target_dc = max(1, min(40, target_dc))

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
    memory_limit = 0
    try:
        memory_limit = max(0, int(top_memory))
    except Exception:
        memory_limit = 0
    if memory_limit > 0 and str(context or "").strip():
        hits = entity.search_memory(str(context), top_n=max(1, memory_limit))
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
    skill_check_log(game_state).append(entry)

    return {
        "success": True,
        "check": entry,
        "memory_hits": memory_hits,
        "skill_check_log_size": len(skill_check_log(game_state)),
    }


def get_recent_skill_checks(
    limit: int = 5,
    game_state: GameState | None = None,
) -> dict[str, object]:
    if game_state is None:
        return {"success": False, "reason": "Missing game_state context."}
    lim = max(1, min(50, int(limit)))
    log = skill_check_log(game_state)
    return {"success": True, "checks": log[-lim:]}


MECHANICS_TOOL_DEFINITIONS = [
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
                    "label": {"type": "string"},
                },
                "required": [],
            },
        },
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
                    "top_memory": {"type": "integer", "minimum": 0, "maximum": 10},
                },
                "required": [],
            },
        },
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
                "required": [],
            },
        },
    },
]


__all__ = [
    "MECHANICS_TOOL_DEFINITIONS",
    "get_recent_skill_checks",
    "roll_dice",
    "skill_check",
]

from __future__ import annotations

from typing import Any, Dict, Optional

from .story import GameState
from .tool_runtime import (
    TODO_ACTIVE_STATUSES,
    TODO_ALLOWED_STATUSES,
    require_turn_orchestration_ctx,
)


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
) -> dict[str, Any]:
    if game_state is None:
        raise RuntimeError("Missing game_state context.")
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty list")

    ctx = require_turn_orchestration_ctx(game_state)
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
) -> dict[str, Any]:
    if game_state is None:
        raise RuntimeError("Missing game_state context.")
    ctx = require_turn_orchestration_ctx(game_state)

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
) -> dict[str, Any]:
    if game_state is None:
        raise RuntimeError("Missing game_state context.")
    ctx = require_turn_orchestration_ctx(game_state)

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

    item["status"] = normalized_status
    item["resolution"] = str(resolution).strip()
    item["used_tool"] = bool(used_tool)

    return {
        "ok": True,
        "item": item,
        "counts": _compute_turn_todo_counts(ctx),
    }


def get_turn_progress(
    game_state: GameState | None = None,
) -> dict[str, Any]:
    if game_state is None:
        raise RuntimeError("Missing game_state context.")
    ctx = require_turn_orchestration_ctx(game_state)
    return {
        "ok": True,
        "phase": str(ctx.get("phase", "")),
        "todo_revision": int(ctx.get("todo_revision", 0)),
        "todo_counts": _compute_turn_todo_counts(ctx),
        "current_location": str(ctx.get("current_location", "")),
        "player_location": getattr(game_state, "player_location", ""),
    }


def add_turn_note(
    text: str,
    game_state: GameState | None = None,
) -> dict[str, Any]:
    if game_state is None:
        raise RuntimeError("Missing game_state context.")
    ctx = require_turn_orchestration_ctx(game_state)

    note = str(text).strip()
    if not note:
        raise ValueError("text cannot be empty")
    notes = ctx.setdefault("notes", [])
    notes.append(note)
    return {"ok": True, "note": note, "total_notes": len(notes)}


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
                                "tool_name": {"type": "string"},
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


__all__ = [
    "TURN_TODO_TOOL_DEFINITIONS",
    "add_turn_note",
    "get_turn_progress",
    "get_turn_todo",
    "set_todo_item_status",
    "set_turn_todo",
]

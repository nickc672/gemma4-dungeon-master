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

def _normalize_intended_actions(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind", "")).strip().lower()
        if not kind:
            continue
        cleaned.append({
            "kind": kind,
            "target": str(entry.get("target", "")).strip(),
            "destination": str(entry.get("destination", "")).strip(),
            "memory_text": str(entry.get("memory_text", "")).strip(),
            "note": str(entry.get("note", "")).strip(),
        })
    return cleaned


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


def finalize_turn(
    turn_summary: str,
    narration_focus: str = "",
    blocked_reason: str = "",
    intended_actions: list | None = None,
    game_state: GameState | None = None,
) -> dict[str, Any]:
    """
    Terminal tool that ends the Phase 1 (read-only) agent loop.
    The model calls this once it has used whatever read tools were needed
    and is ready to hand off to the narrator.

    The payload is stored on the turn ctx under `finalize` and used to build
    the narration prompt and the Phase 2 writer prompt.

    intended_actions is a list of structured hints describing what state
    changes should be applied during Phase 2.
    """
    if game_state is None:
        raise RuntimeError("Missing game_state context.")
    ctx = require_turn_orchestration_ctx(game_state)

    summary = str(turn_summary or "").strip()
    if not summary:
        raise ValueError("turn_summary cannot be empty")

    focus = str(narration_focus or "").strip()
    blocked = str(blocked_reason or "").strip()
    actions = _normalize_intended_actions(intended_actions)

    ctx["finalize"] = {
        "turn_summary": summary,
        "narration_focus": focus,
        "blocked_reason": blocked,
        "intended_actions": actions,
    }
    return {
        "ok": True,
        "turn_summary": summary,
        "narration_focus": focus,
        "blocked_reason": blocked,
        "intended_actions": actions,
    }


def finalize_writes(
    writes_summary: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    """
    Terminal tool that ends the Phase 2 writer loop.
    The model calls this once it has applied all needed state changes
    using the write tools.
    """
    if game_state is None:
        raise RuntimeError("Missing game_state context.")
    ctx = require_turn_orchestration_ctx(game_state)

    summary = str(writes_summary or "").strip()
    ctx["finalize_writes"] = {"writes_summary": summary}
    return {"ok": True, "writes_summary": summary}


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


FINALIZE_TURN_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "finalize_turn",
        "description": (
            "Terminal tool for Phase 1. Call exactly once, last, when all "
            "needed read and mechanics tools have been used and the turn is "
            "resolved. The narrator and the writer phase will run after this "
            "call. State changes (movement, memory writes) are applied later "
            "in Phase 2."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "turn_summary": {
                    "type": "string",
                    "description": (
                        "Short factual recap of what was resolved this turn: "
                        "actions taken, check outcomes, intended state changes."
                    ),
                },
                "narration_focus": {
                    "type": "string",
                    "description": (
                        "One-line hint to the narrator about what should land "
                        "in the player-facing response."
                    ),
                },
                "blocked_reason": {
                    "type": "string",
                    "description": (
                        "If the player's action could not be resolved (e.g. "
                        "invalid target, movement blocked), a short reason; "
                        "otherwise leave empty."
                    ),
                },
                "intended_actions": {
                    "type": "array",
                    "description": (
                        "Structured hints for the writer phase about what "
                        "state changes should be applied. Each item describes "
                        "one intended change."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": [
                                    "player_move",
                                    "npc_move",
                                    "memory_for_entity",
                                ],
                                "description": (
                                    "Type of state change. player_move uses "
                                    "destination. npc_move uses target and "
                                    "destination. memory_for_entity uses "
                                    "target and memory_text."
                                ),
                            },
                            "target": {
                                "type": "string",
                                "description": (
                                    "Entity key for npc_move or "
                                    "memory_for_entity."
                                ),
                            },
                            "destination": {
                                "type": "string",
                                "description": (
                                    "Location key for player_move and npc_move."
                                ),
                            },
                            "memory_text": {
                                "type": "string",
                                "description": (
                                    "Memory sentence for memory_for_entity."
                                ),
                            },
                            "note": {"type": "string"},
                        },
                        "required": ["kind"],
                    },
                },
            },
            "required": ["turn_summary"],
        },
    },
}


FINALIZE_WRITES_TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "finalize_writes",
        "description": (
            "Terminal tool for the Phase 2 writer phase. Call exactly once "
            "after all needed write tools have been used to bring the game "
            "state in line with the narration."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "writes_summary": {
                    "type": "string",
                    "description": (
                        "Short summary of the writes that were applied."
                    ),
                },
            },
            "required": [],
        },
    },
}


__all__ = [
    "FINALIZE_TURN_TOOL_DEFINITION",
    "FINALIZE_WRITES_TOOL_DEFINITION",
    "TURN_TODO_TOOL_DEFINITIONS",
    "add_turn_note",
    "finalize_turn",
    "finalize_writes",
    "get_turn_progress",
    "get_turn_todo",
    "set_todo_item_status",
    "set_turn_todo",
]

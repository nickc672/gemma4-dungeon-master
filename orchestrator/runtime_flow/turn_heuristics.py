from __future__ import annotations
import re
from typing import Any, Dict


# Text section extraction

def _extract_labeled_line(text: str, label: str) -> str:
    pattern = re.compile(rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+?)\s*$")
    match = pattern.search(text or "")
    return match.group(1).strip() if match else ""


def _extract_labeled_block(text: str, label: str) -> str:
    pattern = re.compile(
        rf"(?ims)^\s*{re.escape(label)}\s*:\s*(.*?)(?=^\s*[A-Za-z][A-Za-z _-]*\s*:|\Z)"
    )
    match = pattern.search(text or "")
    return match.group(1).strip() if match else ""


def _extract_bullet_items(text: str, label: str) -> list[str]:
    block = _extract_labeled_block(text, label)
    items: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("- ", "* ")):
            items.append(stripped[2:].strip())
            continue
        numbered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if numbered:
            items.append(numbered.group(1).strip())
    return [item for item in items if item]


def _todo_specs_from_lines(lines: list[str]) -> list[dict[str, Any]]:
    return [{"task": line, "requires_tool": False} for line in lines if str(line).strip()]


def _summary_snippet(text: str, limit: int = 220) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    for sep in (". ", "! ", "? "):
        idx = cleaned.find(sep)
        if 0 < idx < limit:
            return cleaned[: idx + 1]
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."



# Roll / mechanics intent detection

def _mentions_unresolved_roll_request(text: str) -> bool:
    cleaned = " ".join(str(text or "").lower().split())
    if not cleaned:
        return False
    markers = (
        "roll",
        "skill check",
        "make a check",
        "passive perception",
        "dc ",
        "investigation check",
        "perception check",
        "stealth check",
        "persuasion check",
        "athletics check",
    )
    return any(marker in cleaned for marker in markers)


def _turn_has_resolved_roll(turn_ctx: Dict[str, Any]) -> bool:
    """
    True when at least one roll has already fired during this turn, either
    through a direct skill_check call or through a tool that rolled.
    Used to suppress the 'defer roll to narration' guard once a roll exists,
    so the model can reference the prior result in its Decision Summary
    without being blocked for using words like 'roll', 'DC', or 'check'.
    """
    for call in turn_ctx.get("all_world_tool_calls", []) or []:
        name = str(call.get("name") or "").strip()
        result = call.get("result") or {}
        if name == "skill_check" and (result.get("ok") or result.get("success")):
            return True
        if name == "check_can_interact":
            history = result.get("history_check") or {}
            if history.get("rolled"):
                return True
    return False



# Player input intent classification

# Keywords that signal player movement intent.
_MOVEMENT_PHRASES = frozenset([
    "go to", "move to", "walk to", "run to", "travel to", "head to",
    "proceed to", "go back", "return to", "head back", "sneak to",
    "creep to", "rush to", "climb to", "go inside", "go outside",
    "enter the", "leave the", "exit the", "go through", "cross to",
    "explore", "visit",
])

# Keywords that signal significant NPC interaction in a turn summary.
_INTERACTION_WORDS = frozenset([
    "spoke", "talked", "asked", "told", "said", "replied", "mentioned",
    "learned", "revealed", "confessed", "heard", "questioned", "confronted",
    "greeted", "warned", "threatened", "persuaded", "deceived", "admitted",
    "showed", "gave", "traded", "accused", "denied", "discovered",
    "found", "noticed", "examined", "inspected", "investigated",
])

# Trivial player inputs that do not require a memory write.
_TRIVIAL_INPUT_PATTERNS = (
    re.compile(r"^\s*(hi|hello|hey|yo|sup|hiya)\s*[.!?]?\s*$", re.IGNORECASE),
    re.compile(r"^\s*(thanks|thank you|ty)\s*[.!?]?\s*$", re.IGNORECASE),
    re.compile(r"^\s*(ok|okay|alright|sure|yes|no|yep|nope)\s*[.!?]?\s*$", re.IGNORECASE),
    re.compile(r"^\s*(help|menu)\s*[.!?]?\s*$", re.IGNORECASE),
)

# Regex matching any Phase 2 tool name written as text (catches "tool: X" formatting).
_PHASE_2_TOOL_NAME_PATTERN = re.compile(
    r"(?i)\b(tool|function)\s*:\s*"
    r"(move_to_location|write_memory_tool|finalize_writes|move_npc"
    r"|move_world_item|create_npc|create_item)\b"
)


def _is_movement_request(text: str) -> bool:
    lowered = " ".join(str(text or "").lower().split())
    return any(phrase in lowered for phrase in _MOVEMENT_PHRASES)


def _summary_has_interaction(summary: str) -> bool:
    lowered = " ".join(str(summary or "").lower().split())
    return any(word in lowered for word in _INTERACTION_WORDS)


def _is_trivial_player_input(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return True
    return any(pattern.match(cleaned) for pattern in _TRIVIAL_INPUT_PATTERNS)


# Tool call inspection

def _tool_call_succeeded(call: Dict[str, Any]) -> bool:
    result = call.get("result") or {}
    if "ok" in result:
        return bool(result.get("ok"))
    return bool(result.get("success", False))


__all__ = [
    "_extract_labeled_line",
    "_extract_labeled_block",
    "_extract_bullet_items",
    "_todo_specs_from_lines",
    "_summary_snippet",
    "_mentions_unresolved_roll_request",
    "_turn_has_resolved_roll",
    "_is_movement_request",
    "_summary_has_interaction",
    "_is_trivial_player_input",
    "_tool_call_succeeded",
    "_PHASE_2_TOOL_NAME_PATTERN",
]
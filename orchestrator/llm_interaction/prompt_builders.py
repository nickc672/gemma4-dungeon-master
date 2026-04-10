from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class PromptState:
    """Structured prompt context derived from the current runtime world state."""

    history_text: str
    beat_current: str
    beat_next: str
    beat_guide: str
    story_status: str
    session_summary: str
    player_input: str
    current_location: str
    scene_description: str
    connected_locations: List[str] = field(default_factory=list)
    scene_actors: List[str] = field(default_factory=list)
    scene_items: List[str] = field(default_factory=list)
    entity_info: Dict[str, Dict[str, str]] = field(default_factory=dict)



def _recent_history(history_text: str, limit_lines: int = 4) -> str:
    lines = [line.strip() for line in str(history_text or "").splitlines() if line.strip()]
    if not lines:
        return "None"
    return "\n".join(lines[-limit_lines:])


def _latest_recap(summary_text: str) -> str:
    lines = [line.strip() for line in str(summary_text or "").splitlines() if line.strip()]
    return lines[-1] if lines else "None"


def _format_lines(items: List[str], *, empty: str) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in cleaned)


def _scene_snapshot_block(state: PromptState) -> str:
    return (
        f"Current Location: {state.current_location or 'Unknown'}\n"
        f"Scene Description: {state.scene_description or 'Unknown location'}\n"
        f"Actors Here:\n{_format_lines(state.scene_actors, empty='None noted')}\n"
        f"Items Here:\n{_format_lines(state.scene_items, empty='None noted')}\n"
        f"Connected Locations:\n{_format_lines(state.connected_locations, empty='None noted')}"
    )


def _entity_info_block(state: PromptState) -> str:
    if not state.entity_info:
        return "  None"

    lines: list[str] = []
    for key in sorted(state.entity_info):
        info = state.entity_info[key]
        parts = [f"  {key}:"]
        for label in ("node_type", "location", "connections", "inventory", "holder", "flags"):
            value = str(info.get(label, "")).strip()
            if value:
                parts.append(f"    {label}: {value}")
        lines.append("\n".join(parts))
    return "\n".join(lines)


def build_intent_phase_prompt(state: PromptState) -> str:
    return (
        f"# Player Request\n"
        f"{state.player_input}\n\n"
        f"# Current Scene\n"
        f"{_scene_snapshot_block(state)}\n\n"
        f"# Session Recap\n"
        f"{_latest_recap(state.session_summary)}\n\n"
        f"# Recent Conversation\n"
        f"{_recent_history(state.history_text)}"
    )


def build_narrate_prompt(
    state: PromptState,
    plan: str,
    verdict: str,
    notes: str,
    action_results: list[dict] | None = None,
) -> str:
    action_summary = ""
    if action_results:
        lines = []
        for tool_call in action_results:
            result = dict(tool_call.get("result") or {})
            reason = str(result.get("reason") or result.get("message") or "").strip()
            lines.append(f"- {tool_call.get('name')}: {reason or ('Success' if result.get('success') else 'Failed')}")
        action_summary = "\n\n# Actions Executed\n" + "\n".join(lines)

    return f"""# Player Request
{state.player_input}

# Current Scene
{_scene_snapshot_block(state)}

# Session Recap
{_latest_recap(state.session_summary)}

# Recent Conversation
{_recent_history(state.history_text)}

# Resolved Turn State
Intent Summary: {plan}
Resolution Status: {verdict}
Mechanics Summary: {notes}
{action_summary}

---

Now generate a DM response to the player's latest input using the current scene and resolved turn state above.
"""


def build_mechanics_phase_prompt(
    state: PromptState,
    intent_summary: str,
    todo_items: list[dict[str, Any]],
) -> str:
    todo_lines = [
        f"- {str(item.get('task', '')).strip()}"
        for item in todo_items
        if str(item.get("task", "")).strip()
    ]
    if not todo_lines:
        todo_lines = [f"- Resolve the player's declared action in context: {state.player_input}"]
    return (
        f"# Player Request\n"
        f"{state.player_input}\n\n"
        f"# Current Scene\n"
        f"{_scene_snapshot_block(state)}\n\n"
        f"# Intent Summary\n"
        f"{intent_summary or 'Resolve the player request directly and only use tools if needed.'}\n\n"
        f"# Turn Todo\n"
        f"{chr(10).join(todo_lines)}\n\n"
        f"# Session Recap\n"
        f"{_latest_recap(state.session_summary)}"
    )


def build_intro_prompt(state: PromptState) -> str:
    return textwrap.dedent(
        f"""
        Starting State:
        {state.story_status or 'Not set'}

        Beat Guide:
        {state.beat_guide}

        Current Beat:
        {state.beat_current}

        Next Beat:
        {state.beat_next}

        Starting Scene:
        {_scene_snapshot_block(state)}

        Session Summary:
        {state.session_summary or 'None'}

        Conversation So Far:
        {state.history_text or 'No prior conversation.'}
        """
    ).strip()

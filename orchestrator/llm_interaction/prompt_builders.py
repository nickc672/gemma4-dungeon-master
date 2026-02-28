from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from typing import Dict, Any, List


# -------------------------
# Shared Prompt State
# -------------------------

@dataclass
class PromptState:
    """holds a snapshot of story/game state used for building prompts.
    Instead of passing 10+ parameters everywhere, it provides
    a single structured object that prompt builders consume."""
    history_text: str
    active_keys: List[str]
    focus: List[str]
    beat_current: str
    beat_next: str
    beat_guide: str
    story_status: str
    session_summary: str
    intent: Dict[str, Any]
    player_input: str
    entity_info: Dict[str, Dict[str, str]] = field(default_factory=dict)

# -------------------------
# Helpers
# -------------------------

def _format_intent(intent: Dict[str, Any]) -> str:
    action = intent.get("action") or ""
    action_category = intent.get("action_category") or ""
    targets = ", ".join(intent.get("targets") or [])
    category_line = ""
    if action_category and action_category != action:
        category_line = f"\nAction_Category: {action_category}"
    return (
        f"Action: {action}"
        f"{category_line}"
        f"\nTargets: {targets or 'None'}"
    )


def _current_location(state: PromptState) -> str:
    return state.focus[0] if state.focus else "Unknown"


def _recent_history(history_text: str, limit_lines: int = 4) -> str:
    lines = [line.strip() for line in str(history_text or "").splitlines() if line.strip()]
    if not lines:
        return "None"
    return "\n".join(lines[-limit_lines:])


def _latest_recap(summary_text: str) -> str:
    lines = [line.strip() for line in str(summary_text or "").splitlines() if line.strip()]
    return lines[-1] if lines else "None"


def _scene_context(state: PromptState) -> tuple[list[str], list[str]]:
    current_location = _current_location(state)
    immediate_lines: list[str] = []
    nearby_locations: list[str] = []

    for key in sorted(state.entity_info):
        info = state.entity_info[key]
        node_type = info.get("node_type", "unknown")
        location = info.get("location", "unknown")
        if key == current_location or location == current_location:
            if key != current_location:
                immediate_lines.append(f"- {key} ({node_type})")
            continue
        if node_type == "location":
            nearby_locations.append(f"- {key}")

    if not immediate_lines:
        immediate_lines = ["- None noted"]
    if not nearby_locations:
        nearby_locations = ["- None"]

    return immediate_lines, nearby_locations[:6]


# -------------------------
# Prompt Builders
# -------------------------

def build_intent_prompt(history_text: str, player_input: str) -> str:
    return textwrap.dedent(
        f"""
        # Recent Conversation
        {history_text or 'No prior conversation.'}

        # Player Input
        {player_input}
        """
    ).strip()


def build_focus_prompt(state: PromptState) -> str:
    keys = ", ".join(state.active_keys)
    return textwrap.dedent(
        f"""
        # Intent
        {_format_intent(state.intent)}

        # Available Nodes
        {keys}

        # Player Input
        {state.player_input}
        """
    ).strip()


def build_plan_prompt(state: PromptState) -> str:
    keys = ", ".join(state.active_keys)

    return textwrap.dedent(
        f"""
        # Intent
        {_format_intent(state.intent)}

        # Beat (background pacing only; do not force advancement)
        Current: {state.beat_current}
        Next: {state.beat_next}
        Guide: {state.beat_guide}

        # Scene
        Location/Focus: {', '.join(state.focus) or 'None'}
        Relevant World Context Keys (not all are necessarily visible right now): {keys or 'None'}
        Status: {state.story_status or 'Not set'}
        Session Summary: {state.session_summary}

        # Recent Conversation
        {state.history_text or 'No prior conversation.'}

        # Player Input
        {state.player_input}
        """
    ).strip()


def build_intent_phase_prompt(state: PromptState) -> str:
    current_location = _current_location(state)
    immediate_lines, nearby_locations = _scene_context(state)
    return (
        f"# Player Request\n"
        f"{state.player_input}\n\n"
        f"# Parsed Intent\n"
        f"{_format_intent(state.intent)}\n\n"
        f"# Scene Snapshot\n"
        f"Current Location: {current_location}\n"
        f"Immediate Context:\n{chr(10).join(immediate_lines)}\n"
        f"Nearby Known Locations:\n{chr(10).join(nearby_locations)}\n\n"
        f"# Session Recap\n"
        f"{_latest_recap(state.session_summary)}\n\n"
        f"# Recent Conversation\n"
        f"{_recent_history(state.history_text)}"
    )


def build_validate_prompt(state: PromptState, plan: str) -> str:
    keys = ", ".join(state.active_keys)

    # entity info block 
    entity_lines = []
    for key, info in state.entity_info.items():
        parts = [f"  {key}:"]
        if info.get("location"):
            parts.append(f"    location: {info['location']}")
        if info.get("status"):
            parts.append(f"    status: {info['status']}")
        if info.get("node_type"):
            parts.append(f"    type: {info['node_type']}")
        if info.get("connections"):
            parts.append(f"    connections: {info['connections']}")
        entity_lines.append("\n".join(parts))

    entity_block = "\n".join(entity_lines) if entity_lines else "  None"


    return textwrap.dedent(
        f"""
        # Intent
        {_format_intent(state.intent)}

        # Beat
        Current: {state.beat_current}
        Next: {state.beat_next}
        Guide: {state.beat_guide}

        # Scene
        Location/Focus: {', '.join(state.focus) or 'None'}
        Active Context Keys: {keys or 'None'}
        Status: {state.story_status or 'Not set'}
        Session Summary: {state.session_summary}

        # Recent Conversation
        {state.history_text or 'No prior conversation.'}

        # Player Input
        {state.player_input}

        # Entity Information
        {entity_block}
        
        # Proposed Plan
        {plan}

        """
    ).strip()


def build_narrate_prompt(
    state: PromptState,
    plan: str,
    verdict: str,
    notes: str,
    action_results: list[dict] = None,
) -> str:
    """Build the narration prompt with action results."""

    current_location = _current_location(state)
    immediate_context_lines, nearby_locations = _scene_context(state)

    action_summary = ""
    if action_results:
        action_summary = "\n\n# Actions Executed\n"
        for tool_call in action_results:
            result = tool_call["result"]
            if result.get("success"):
                action_summary += f"{tool_call['name']}: {result.get('reason', 'Success')}\n"
            else:
                action_summary += f"{tool_call['name']}: {result.get('reason', 'Failed')}\n"
    
    return f"""# Player Request
{state.player_input}

# Current Scene
Player's Current Location: {current_location}
Immediate Context:
{chr(10).join(immediate_context_lines)}
Nearby Known Locations:
{chr(10).join(nearby_locations)}

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

Now generate a DM response to the player's latest input using the CURRENT story context above.
"""


def build_mechanics_phase_prompt(
    state: PromptState,
    intent_summary: str,
    todo_items: list[dict[str, Any]],
) -> str:
    current_location = _current_location(state)
    immediate_lines, nearby_locations = _scene_context(state)
    todo_lines = [f"- {str(item.get('task', '')).strip()}" for item in todo_items if str(item.get("task", "")).strip()]
    if not todo_lines:
        todo_lines = [f"- Resolve the player's declared action in context: {state.player_input}"]
    return (
        f"# Player Request\n"
        f"{state.player_input}\n\n"
        f"# Parsed Intent\n"
        f"{_format_intent(state.intent)}\n\n"
        f"# Scene Snapshot\n"
        f"Current Location: {current_location}\n"
        f"Immediate Context:\n{chr(10).join(immediate_lines)}\n"
        f"Nearby Known Locations:\n{chr(10).join(nearby_locations)}\n\n"
        f"# Intent Summary\n"
        f"{intent_summary or 'Resolve the player request directly and only use tools if needed.'}\n\n"
        f"# Turn Todo\n"
        f"{chr(10).join(todo_lines)}\n\n"
        f"# Session Recap\n"
        f"{_latest_recap(state.session_summary)}"
    )


def build_status_prompt(state: PromptState) -> str:
    keys = ", ".join(state.active_keys)

    return textwrap.dedent(
        f"""
        Current Focus:
        {', '.join(state.focus) or 'None'}

        Active Context Keys:
        {keys or 'None'}

        Beat:
        {state.beat_current}

        Session Summary:
        {state.session_summary}

        Conversation So Far:
        {state.history_text or 'No prior conversation.'}
        """
    ).strip()


def build_intro_prompt(state: PromptState) -> str:
    keys = ", ".join(state.active_keys)

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

        Focus:
        {', '.join(state.focus) or 'None'}

        Active Context Keys:
        {keys or 'None'}

        Session Summary:
        {state.session_summary}

        Conversation So Far:
        {state.history_text or 'No prior conversation.'}
        """
    ).strip()

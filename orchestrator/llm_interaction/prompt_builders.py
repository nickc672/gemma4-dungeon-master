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
    refusals = ", ".join(intent.get("refusals") or [])
    category_line = ""
    if action_category and action_category != action:
        category_line = f"\nAction_Category: {action_category}"
    return (
        f"\nAction: {action}"
        f"{category_line}"
        f"\nTargets: {targets or 'None'}"
        f"\nRefusals: {refusals or 'None'}"
    )


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
        Relevant Graph Nodes (not all are necessarily visible right now): {keys or 'None'}
        Status: {state.story_status or 'Not set'}
        Session Summary: {state.session_summary}

        # Recent Conversation
        {state.history_text or 'No prior conversation.'}

        # Player Input
        {state.player_input}
        """
    ).strip()


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
        Active Nodes: {keys or 'None'}
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

    current_location = state.focus[0] if state.focus else "Unknown"
    immediate_context_lines: list[str] = []
    related_context_lines: list[str] = []
    for key in sorted(state.entity_info):
        info = state.entity_info[key]
        node_type = info.get("node_type", "unknown")
        location = info.get("location", "unknown")
        line = f"- {key} ({node_type}, location={location})"
        if location == current_location or key == current_location:
            immediate_context_lines.append(line)
        else:
            related_context_lines.append(line)

    if not immediate_context_lines:
        immediate_context_lines = ["- None"]
    if not related_context_lines:
        related_context_lines = ["- None"]

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

# Story Context

Player's Current Location: {current_location}

Immediate Context Entities (grounding hints for the current location):
{chr(10).join(immediate_context_lines)}

Related World Context (relevant graph/entity context; may include adjacent or non-visible items):
{chr(10).join(related_context_lines)}

Relevant Graph Nodes (not guaranteed visible):
{chr(10).join(f"- {key}" for key in state.active_keys)}

# Beat (background pacing only)
Current: {state.beat_current}
Next: {state.beat_next}

# Recent Conversation
{state.history_text}

# Plan
{plan}

# Validation
Verdict: {verdict}
Notes: {notes}
{action_summary}

---

Now generate a DM response to the player's latest input using the CURRENT story context above.
"""


def build_status_prompt(state: PromptState) -> str:
    keys = ", ".join(state.active_keys)

    return textwrap.dedent(
        f"""
        Current Focus:
        {', '.join(state.focus) or 'None'}

        Active Nodes:
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

        Active Nodes:
        {keys or 'None'}

        Session Summary:
        {state.session_summary}

        Conversation So Far:
        {state.history_text or 'No prior conversation.'}
        """
    ).strip()

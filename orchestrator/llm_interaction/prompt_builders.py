from __future__ import annotations

import textwrap
from dataclasses import dataclass
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


# -------------------------
# Helpers
# -------------------------

def _format_intent(intent: Dict[str, Any]) -> str:
    action = intent.get("action") or ""
    targets = ", ".join(intent.get("targets") or [])
    refusals = ", ".join(intent.get("refusals") or [])
    return (
        f"\nAction: {action}"
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
        """
    ).strip()


def build_validate_prompt(state: PromptState, plan: str) -> str:
    keys = ", ".join(state.active_keys)

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

        # Entity Hints
        Focus Entities: {', '.join(state.focus) or 'None'}
        Candidate Entities: {keys or 'None'}
        
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
    
    action_summary = ""
    if action_results:
        action_summary = "\n\n# Actions Executed\n"
        for tool_call in action_results:
            result = tool_call["result"]
            if result.get("success"):
                action_summary += f"{tool_call['name']}: {result.get('reason', 'Success')}\n"
            else:
                action_summary += f"{tool_call['name']}: {result.get('reason', 'Failed')}\n"
    
    return f"""# Story Context

Player's Current Location: {state.focus[0] if state.focus else "Unknown"}

Active Story Nodes (available for this scene):
{chr(10).join(f"- {key}" for key in state.active_keys)}

# Beat
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

Now generate the narrative response based on the CURRENT story context above.
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


from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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


@dataclass
class PromptConfig:
    """
    Boolean flags controlling what context each phase receives.

    Phase 1 (agent prompt)
    p1_story_status          - the running story/status paragraph
    p1_scene_description     - the prose description of the current location
    p1_scene_actors          - actor names present in the scene
    p1_scene_items           - item names present in the scene
    p1_connected_locations   - names of reachable adjacent locations
    p1_entity_info           - full world-state block with connections, inventories, flags etc. (expensive)
    p1_session_recap         - multi-turn condensed recap
    p1_recent_conversation   - last N lines of player/DM exchange

    Narration prompt
    narrate_scene            - current location + actors/items/connections
    narrate_entity_info      - full world-state block (the narrator does not need deep world detail)
    narrate_story_status     - story/status paragraph (for tone)
    narrate_session_recap    - multi-turn condensed recap
    narrate_recent_conversation - last N lines of exchange (for continuity)

    Phase 2 (writer prompt)
    p2_scene                 - current scene snapshot (pre-write)
    p2_action_results        - Phase 1 tool results (rolls, checks)
    p2_player_location_before - where the player was before this turn
    """

    # Phase 1
    p1_story_status: bool = True
    p1_scene_description: bool = True
    p1_scene_actors: bool = True
    p1_scene_items: bool = True
    p1_connected_locations: bool = True
    p1_entity_info: bool = False
    p1_session_recap: bool = True
    p1_recent_conversation: bool = True

    # Narration
    narrate_scene: bool = True
    narrate_entity_info: bool = False
    narrate_story_status: bool = True
    narrate_session_recap: bool = False
    narrate_recent_conversation: bool = True

    # Phase 2
    p2_scene: bool = True
    p2_action_results: bool = True
    p2_player_location_before: bool = True


DEFAULT_PROMPT_CONFIG = PromptConfig()


def _recent_history(history_text: str, limit_lines: int = 4) -> str:
    lines = [line.strip() for line in str(history_text or "").splitlines() if line.strip()]
    if not lines:
        return "None"
    return "\n".join(lines[-limit_lines:])


def _recent_recap(summary_text: str, limit_lines: int = 4) -> str:
    lines = [line.strip() for line in str(summary_text or "").splitlines() if line.strip()]
    if not lines:
        return "None"
    return "\n".join(lines[-limit_lines:])


def _format_lines(items: List[str], *, empty: str) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in cleaned)


def _args_summary(args: dict) -> str:
    """Compact one-line summary of tool call arguments for display in prompts."""
    parts = []
    for k, v in (args or {}).items():
        if k.startswith("_"):
            continue
        val = str(v)
        if len(val) > 40:
            val = val[:40] + "…"
        parts.append(f"{k}={val!r}")
    return ", ".join(parts)


def _format_tool_call_log(tool_calls: list[dict] | None) -> str:
    """Format a list of tool call dicts into a readable log string."""
    if not tool_calls:
        return "- (none)"
    lines = []
    for call in tool_calls:
        result = call.get("result") or {}
        ok = result.get("ok")
        if ok is None:
            ok = result.get("success", True)
        label = "ok" if ok else "FAIL"
        reason = str(result.get("reason") or result.get("message") or "").strip()
        args_str = _args_summary(call.get("arguments") or {})
        entry = f"- {call.get('name')}({args_str}): {label}"
        if reason:
            entry += f" — {reason}"
        lines.append(entry)
    return "\n".join(lines)


def _scene_snapshot_block(
    state: PromptState,
    *,
    include_description: bool = True,
    include_actors: bool = True,
    include_items: bool = True,
    include_connections: bool = True,
) -> str:
    parts = [f"Current Location: {state.current_location or 'Unknown'}"]
    if include_description:
        parts.append(f"Scene Description: {state.scene_description or 'Unknown location'}")
    if include_actors:
        parts.append(f"Actors Here:\n{_format_lines(state.scene_actors, empty='None noted')}")
    if include_items:
        parts.append(f"Items Here:\n{_format_lines(state.scene_items, empty='None noted')}")
    if include_connections:
        parts.append(f"Connected Locations:\n{_format_lines(state.connected_locations, empty='None noted')}")
    return "\n".join(parts)


def _entity_info_block(state: PromptState) -> str:
    if not state.entity_info:
        return "  None"

    lines: list[str] = []
    for key in sorted(state.entity_info):
        info = state.entity_info[key]
        parts = [f"  {key}:"]
        for label in ("node_type", "location", "connections", "inventory", "holder", "discovered", "flags"):
            value = str(info.get(label, "")).strip()
            if value:
                parts.append(f"    {label}: {value}")
        lines.append("\n".join(parts))
    return "\n".join(lines)


# =====================================
# Phase 1 - agent prompt
# =====================================

def build_agent_prompt(
    state: PromptState,
    cfg: PromptConfig = DEFAULT_PROMPT_CONFIG,
) -> str:
    sections: list[str] = []

    sections.append(f"# Player Request\n{state.player_input}")

    if cfg.p1_story_status:
        sections.append(
            f"# Story Status\n{state.story_status or 'No current story status recorded.'}"
        )

    if any([cfg.p1_scene_description, cfg.p1_scene_actors, cfg.p1_scene_items, cfg.p1_connected_locations]):
        sections.append(
            f"# Current Scene\n"
            + _scene_snapshot_block(
                state,
                include_description=cfg.p1_scene_description,
                include_actors=cfg.p1_scene_actors,
                include_items=cfg.p1_scene_items,
                include_connections=cfg.p1_connected_locations,
            )
        )

    if cfg.p1_entity_info:
        sections.append(f"# Relevant World State\n{_entity_info_block(state)}")

    if cfg.p1_session_recap:
        sections.append(f"# Session Recap\n{_recent_recap(state.session_summary)}")

    if cfg.p1_recent_conversation:
        sections.append(f"# Recent Conversation\n{_recent_history(state.history_text, limit_lines=6)}")

    return "\n\n".join(sections)


# =====================================
# Narration prompt
# =====================================

def build_narrate_prompt(
    state: PromptState,
    *,
    turn_summary: str,
    narration_focus: str,
    blocked_reason: str,
    action_results: list[dict] | None = None,
    phase_one_tool_calls: list[dict] | None = None,
    cfg: PromptConfig = DEFAULT_PROMPT_CONFIG,
) -> str:
    sections: list[str] = []

    sections.append(f"# Player Request\n{state.player_input}")

    if cfg.narrate_scene:
        sections.append(
            f"# Current Scene\n"
            + _scene_snapshot_block(
                state,
                include_description=True,
                include_actors=True,
                include_items=True,
                include_connections=True,
            )
        )

    if cfg.narrate_entity_info:
        sections.append(f"# Relevant World State\n{_entity_info_block(state)}")

    if cfg.narrate_story_status:
        sections.append(
            f"# Story Status\n{state.story_status or 'No current story status recorded.'}"
        )

    if cfg.narrate_session_recap:
        sections.append(f"# Session Recap\n{_recent_recap(state.session_summary)}")

    if cfg.narrate_recent_conversation:
        sections.append(
            f"# Recent Conversation\n{_recent_history(state.history_text, limit_lines=6)}"
        )

    action_summary = ""
    if action_results:
        lines = []
        for tool_call in action_results:
            result = dict(tool_call.get("result") or {})
            reason = str(result.get("reason") or result.get("message") or "").strip()
            success = result.get("ok")
            if success is None:
                success = result.get("success", True)
            label = "Success" if success else "Failed"
            lines.append(f"- {tool_call.get('name')}: {reason or label}")
        action_summary = "\n\n# Phase 1 Mechanics\n" + "\n".join(lines)

    # Full Phase 1 tool call log
    tool_log = ""
    if phase_one_tool_calls:
        tool_log = "\n\n# Phase 1 Tool Call Log\n" + _format_tool_call_log(phase_one_tool_calls)

    focus_block = str(narration_focus).strip() or "(none)"
    blocked_block = f"\nBlocked Reason: {blocked_reason}" if str(blocked_reason).strip() else ""

    sections.append(
        f"# Resolved Turn\n"
        f"Turn Summary: {turn_summary}\n"
        f"Narration Focus: {focus_block}"
        f"{blocked_block}"
        f"{action_summary}"
        f"{tool_log}"
    )

    sections.append(
        "Now generate a DM response to the player's latest input using the current scene and the resolved turn above."
    )

    return "\n\n".join(sections)


# =====================================
# Phase 2 - writer prompt
# =====================================

def build_phase_two_prompt(
    state: PromptState,
    *,
    turn_summary: str,
    narration_focus: str,
    blocked_reason: str,
    phase_one_tool_calls: list[dict] | None,
    narration: str,
    action_results: list[dict] | None,
    world_before: dict,
    cfg: PromptConfig = DEFAULT_PROMPT_CONFIG,
) -> str:
    tool_log = _format_tool_call_log(phase_one_tool_calls)

    action_lines: list[str] = []
    if cfg.p2_action_results:
        for entry in action_results or []:
            name = str(entry.get("name", "")).strip()
            result = entry.get("result") or {}
            reason = str(result.get("reason") or result.get("message") or "").strip()
            success = result.get("ok")
            if success is None:
                success = result.get("success", True)
            label = "ok" if success else "failed"
            if reason:
                action_lines.append(f"- {name}: {label} - {reason}")
            else:
                action_lines.append(f"- {name}: {label}")
    if not action_lines:
        action_lines.append("- (none)")

    blocked_block = f"\nBlocked Reason: {blocked_reason}" if str(blocked_reason).strip() else ""

    sections: list[str] = []

    sections.append(f"# Player Request\n{state.player_input}")

    sections.append(
        f"# Phase 1 Summary\n"
        f"Turn Summary: {turn_summary}\n"
        f"Narration Focus: {narration_focus or '(none)'}"
        f"{blocked_block}"
    )

    sections.append(f"# Narration Shown to Player\n{narration}")

    sections.append(f"# Phase 1 Tool Call Log\n{tool_log}")

    sections.append(
        f"# Phase 1 Mechanics Results (rolls, checks)\n" + "\n".join(action_lines)
    )

    if cfg.p2_player_location_before:
        sections.append(
            f"# Player Location Before This Turn\n{world_before.get('player_location', '')}"
        )

    if cfg.p2_scene:
        sections.append(
            f"# Current Scene (pre-write)\n"
            + _scene_snapshot_block(
                state,
                include_description=False,
                include_actors=True,
                include_items=True,
                include_connections=True,
            )
        )

    sections.append(
        "Apply the writes required to make game state match the narration above. "
        "Use one tool call per response. Call finalize_writes when done."
    )

    return "\n\n".join(sections)


# =====================================
# Intro prompt
# =====================================

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

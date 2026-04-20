from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st


def load_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        st.warning(f"Snapshot file not found: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        st.error(f"Failed to read snapshot: {exc}")
        return {}


def build_dot(snapshot: dict[str, Any]) -> str:
    nodes = snapshot.get("nodes") or []
    edges = snapshot.get("edges") or []
    lines = ["graph Story {", '  graph [bgcolor="transparent"];', "  rankdir=LR;"]
    for node in nodes:
        key = str(node.get("key") or "").strip()
        if not key:
            continue
        flags = node.get("flags") or {}
        attrs = []
        if flags.get("current_location"):
            attrs.extend(['color="#2563eb"', 'style="filled"', 'fillcolor="#dbeafe"'])
        elif flags.get("in_scene"):
            attrs.extend(['color="#6b7280"', 'style="filled"', 'fillcolor="#f3f4f6"'])
        elif flags.get("discovered"):
            attrs.append('color="#9ca3af"')
        label = key.replace('"', '\\"')
        attr_text = ", ".join(attrs)
        if attr_text:
            lines.append(f'  "{label}" [{attr_text}];')
        else:
            lines.append(f'  "{label}";')
    for edge in edges:
        src = str(edge.get("src") or "").strip()
        dst = str(edge.get("dst") or "").strip()
        if src and dst:
            lines.append(f'  "{src.replace(chr(34), r"\\\"")}" -- "{dst.replace(chr(34), r"\\\"")}";')
    lines.append("}")
    return "\n".join(lines)


def list_turn_files(session_dir: Path) -> list[Path]:
    if not session_dir.exists():
        st.warning(f"Session folder not found: {session_dir}")
        return []
    return sorted(session_dir.glob("turn_*.json"))


def summarize_turn_label(snapshot: dict[str, Any], filename: str) -> str:
    turn_number = int(snapshot.get("turn", 0) or 0)
    summary = " ".join(str(snapshot.get("last_turn", {}).get("turn_summary") or "").split()).strip()
    if len(summary) > 60:
        summary = summary[:60].rstrip() + "..."
    return f"{filename} | Turn {turn_number} | {summary or 'No summary'}"


def render_trace_messages(messages: list[dict[str, Any]]) -> None:
    if not messages:
        st.info("No loop message history was stored in this snapshot.")
        return
    for index, message in enumerate(messages, start=1):
        role = str(message.get("role") or "unknown").title()
        with st.expander(f"{index}. {role}", expanded=False):
            if message.get("tool_calls"):
                st.json(message.get("tool_calls"), expanded=False)
            content = str(message.get("content") or "").strip()
            st.code(content or "<empty>", language="markdown")


def render_agent_rounds(rounds: list[dict[str, Any]]) -> None:
    if not rounds:
        st.info("No agent loop rounds were stored in this snapshot.")
        return
    for round_info in rounds:
        iteration = int(round_info.get("iteration", 0) or 0)
        with st.expander(f"Iteration {iteration}", expanded=False):
            if round_info.get("assistant_text"):
                st.markdown("**Assistant Response**")
                st.code(str(round_info.get("assistant_text") or ""), language="markdown")
            if round_info.get("assistant_thinking"):
                st.markdown("**Assistant Thinking**")
                st.code(str(round_info.get("assistant_thinking") or ""), language="markdown")
            if round_info.get("tool_calls"):
                st.markdown("**Tool Calls**")
                st.json(round_info.get("tool_calls"), expanded=False)
            if round_info.get("tool_results"):
                st.markdown("**Tool Results**")
                st.json(round_info.get("tool_results"), expanded=False)
            if round_info.get("hook_notes"):
                st.markdown("**Hook Notes**")
                st.json(round_info.get("hook_notes"), expanded=False)


def flatten_memory_delta(last_turn: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    reconciliation = dict(last_turn.get("reconciliation") or {})
    delta = dict(reconciliation.get("delta") or {})
    for change in delta.get("memory_changes") or []:
        entity = str(change.get("entity") or "")
        for line in change.get("added") or []:
            rows.append({"entity": entity, "change": "added", "memory": str(line)})
        for line in change.get("removed") or []:
            rows.append({"entity": entity, "change": "removed", "memory": str(line)})
    return rows


def main() -> None:
    st.set_page_config(page_title="DMAI Session Viewer", layout="wide")

    st.title("Session State Viewer")
    session_dir_str = st.text_input("Session folder", "state")
    session_dir = Path(session_dir_str)
    turn_files = list_turn_files(session_dir)

    snapshots_by_name = {path.name: load_snapshot(path) for path in turn_files}
    turn_labels = [summarize_turn_label(snapshots_by_name[path.name], path.name) for path in turn_files]
    selected_index = len(turn_labels) - 1 if turn_labels else 0
    selected_label = st.selectbox("Select turn file", turn_labels, index=selected_index) if turn_labels else None

    if not turn_files or selected_label is None:
        st.info("No turn files found yet.")
        return

    selected_name = turn_files[turn_labels.index(selected_label)].name
    snapshot = snapshots_by_name.get(selected_name) or {}
    if not snapshot:
        return

    last_turn = dict(snapshot.get("last_turn") or {})
    llm_trace = dict(last_turn.get("llm_trace") or {})
    agent_trace = dict(llm_trace.get("AGENT") or {})
    reconciliation = dict(last_turn.get("reconciliation") or {})

    overview_tab, turn_tab, records_tab, raw_tab = st.tabs(["Overview", "Turn", "Records", "Raw"])

    with overview_tab:
        cols = st.columns(4)
        beat = snapshot.get("beat_state") or {}
        with cols[0]:
            st.metric("Turn", int(snapshot.get("turn", 0) or 0))
        with cols[1]:
            st.metric("Location", str(snapshot.get("current_location") or "Unknown"))
        with cols[2]:
            st.metric("Beat", f"{int(beat.get('current_index', 0)) + 1}/{int(beat.get('total', 0) or 0)}")
        with cols[3]:
            st.metric("Memory Rows", len(flatten_memory_delta(last_turn)))

        st.subheader("Story Status")
        st.write(str(snapshot.get("story_status") or "No status recorded."))

        st.subheader("Session Summary")
        st.text(str(snapshot.get("session_summary") or "No summary yet."))

        with st.expander("Conversation History", expanded=False):
            for turn in snapshot.get("history") or []:
                st.markdown(f"**{turn.get('role', '').title()}:** {turn.get('content', '')}")

        with st.expander("World Graph", expanded=False):
            st.graphviz_chart(build_dot(snapshot), use_container_width=True)

    with turn_tab:
        if not last_turn:
            st.info("This snapshot does not include a captured turn payload.")
        else:
            summary_tab, messages_tab, rounds_tab, world_tab, memory_tab = st.tabs(
                ["Summary", "LLM Messages", "LLM Rounds", "World Delta", "Memory"]
            )

            with summary_tab:
                st.markdown(f"**Turn Summary:** {last_turn.get('turn_summary') or 'None'}")
                if str(last_turn.get("blocked_reason") or "").strip():
                    st.markdown(f"**Blocked Reason:** {last_turn.get('blocked_reason')}")
                st.markdown("**Narration**")
                st.write(str(last_turn.get("narration", {}).get("ic") or "").strip() or "No narration recorded.")
                if agent_trace.get("prompt"):
                    with st.expander("Agent Prompt", expanded=False):
                        st.code(str(agent_trace.get("prompt") or ""), language="markdown")
                if llm_trace.get("NARRATE", {}).get("prompt"):
                    with st.expander("Narration Prompt", expanded=False):
                        st.code(str(llm_trace.get("NARRATE", {}).get("prompt") or ""), language="markdown")
                if last_turn.get("tool_calls"):
                    with st.expander("Action Tool Calls", expanded=False):
                        st.json(last_turn.get("tool_calls"), expanded=False)
                if last_turn.get("world_tool_calls"):
                    with st.expander("All World Tool Calls", expanded=False):
                        st.json(last_turn.get("world_tool_calls"), expanded=False)

            with messages_tab:
                render_trace_messages(list(agent_trace.get("messages") or []))

            with rounds_tab:
                render_agent_rounds(list(agent_trace.get("rounds") or []))

            with world_tab:
                if reconciliation:
                    st.json(reconciliation, expanded=False)
                else:
                    st.info("No reconciliation payload was stored for this turn.")

            with memory_tab:
                memory_rows = flatten_memory_delta(last_turn)
                if memory_rows:
                    st.dataframe(memory_rows, use_container_width=True)
                else:
                    st.info("No memory delta was stored for this turn.")
                if snapshot.get("memory"):
                    with st.expander("Current Memory Store", expanded=False):
                        st.json(snapshot.get("memory"), expanded=False)

    with records_tab:
        world_records = snapshot.get("world_records") or {}
        st.markdown("**Game State**")
        st.json(snapshot.get("game_state") or {}, expanded=False)
        st.markdown("**Story Record**")
        st.json(world_records.get("story") or {}, expanded=False)
        st.markdown("**Locations**")
        st.dataframe(world_records.get("locations") or [], use_container_width=True)
        st.markdown("**Entities**")
        st.dataframe(world_records.get("entities") or [], use_container_width=True)
        st.markdown("**Items**")
        st.dataframe(world_records.get("items") or [], use_container_width=True)

    with raw_tab:
        st.json(snapshot, expanded=False)


if __name__ == "__main__":
    main()

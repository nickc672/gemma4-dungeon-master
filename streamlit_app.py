from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

import streamlit as st

from orchestrator.app_config import (
    get_ollama_default_model,
    get_ollama_model_choices,
    get_roll_mode,
)
from orchestrator.runtime_flow.pipeline import StoryEngine
from orchestrator.world_state.entity import DynamicSentenceMemory
from orchestrator.world_state.entity_tools import retrieve_memory_tool
from orchestrator.world_state.world_model import WorldModel, build_world_model

ROLL_REQUIRED_SENTINEL = "__DMC_ROLL_REQUIRED__"
ENGINE_ERROR_MESSAGE = "The Dungeon Master is unavailable right now."


@dataclass(frozen=True)
class SessionConfig:
    model: str
    starting_location: str
    starting_state: str
    roll_mode: str

    def reset_signature(self) -> str:
        return "|".join(
            [
                self.starting_location.strip(),
                self.starting_state.strip(),
                self.roll_mode.strip().lower(),
            ]
        )


@dataclass(frozen=True)
class DisplayOptions:
    show_debug_trace: bool


@st.cache_resource
def load_world_defaults() -> WorldModel:
    return build_world_model()


def get_installed_ollama_models() -> list[str]:
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    if result.returncode != 0 or not result.stdout.strip():
        return []

    models: list[str] = []
    for line in result.stdout.splitlines():
        row = line.strip()
        if not row or row.startswith("NAME"):
            continue
        model = row.split()[0].strip()
        if model and model not in models:
            models.append(model)
    return models


def get_model_choices() -> list[str]:
    choices = get_ollama_model_choices()
    for installed_model in get_installed_ollama_models():
        if installed_model not in choices:
            choices.append(installed_model)
    return choices


def ensure_runtime_state() -> None:
    defaults = {
        "messages": [],
        "last_turn": {},
        "pending_player_input": None,
        "awaiting_manual_roll": False,
        "captured_manual_roll": None,
        "latched_manual_roll": None,
        "roll_request": {},
        "config_signature": "",
        "active_model": "",
        "ui_notice": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def clear_manual_roll_state(*, clear_pending_input: bool) -> None:
    st.session_state.awaiting_manual_roll = False
    st.session_state.captured_manual_roll = None
    st.session_state.latched_manual_roll = None
    st.session_state.roll_request = {}
    if clear_pending_input:
        st.session_state.pending_player_input = None


def resolve_roll_notation(request: dict[str, Any] | None) -> str:
    payload = dict(request or {})
    tool_name = str(payload.get("tool_name") or "").strip()
    arguments = dict(payload.get("arguments") or {})
    if tool_name != "roll_dice":
        return "1d20"
    try:
        count = int(arguments.get("count", 1))
        sides = int(arguments.get("sides", 20))
    except (TypeError, ValueError):
        return "1d20"
    return f"{count}d{sides}"


def resolve_roll_max_face(request: dict[str, Any] | None) -> int:
    payload = dict(request or {})
    tool_name = str(payload.get("tool_name") or "").strip()
    arguments = dict(payload.get("arguments") or {})
    if tool_name != "roll_dice":
        return 20
    try:
        sides = int(arguments.get("sides", 20))
    except (TypeError, ValueError):
        return 20
    return max(2, min(1000, sides))


def activate_roll_request(request: dict[str, Any] | None) -> None:
    st.session_state.awaiting_manual_roll = True
    st.session_state.captured_manual_roll = None
    st.session_state.latched_manual_roll = None
    st.session_state.roll_request = {
        "notation": resolve_roll_notation(request),
        "max_face": resolve_roll_max_face(request),
    }


def streamlit_manual_roll_provider(request: dict[str, Any]) -> int:
    latched_roll = st.session_state.get("latched_manual_roll")
    if latched_roll is not None:
        return int(latched_roll)

    captured_roll = st.session_state.get("captured_manual_roll")
    if captured_roll is None:
        activate_roll_request(request)
        raise RuntimeError(ROLL_REQUIRED_SENTINEL)

    value = int(captured_roll)
    st.session_state.captured_manual_roll = None
    st.session_state.latched_manual_roll = value
    st.session_state.awaiting_manual_roll = False
    st.session_state.roll_request = {}
    return value


def initialize_session(config: SessionConfig) -> None:
    engine = StoryEngine(
        model=config.model,
        starting_location=config.starting_location,
        starting_state=config.starting_state,
        roll_mode=config.roll_mode,
        manual_roll_provider=streamlit_manual_roll_provider if config.roll_mode == "manual" else None,
    )

    intro_text = config.starting_state
    try:
        intro = engine.generate_intro()
        intro_text = str(intro.get("ic") or config.starting_state).strip()
    except Exception:
        st.warning("Intro generation failed. Using the configured starting state instead.")

    st.session_state.orchestrator = engine
    st.session_state.messages = [{"role": "assistant", "content": intro_text}]
    st.session_state.last_turn = {}
    st.session_state.config_signature = config.reset_signature()
    st.session_state.active_model = config.model
    clear_manual_roll_state(clear_pending_input=True)


def ensure_session(config: SessionConfig, *, reset_requested: bool) -> None:
    current_signature = config.reset_signature()
    if "orchestrator" not in st.session_state:
        initialize_session(config)
        return
    if reset_requested:
        initialize_session(config)


def sync_engine_model(engine: StoryEngine, model: str) -> None:
    selected_model = str(model or "").strip()
    if not selected_model:
        return
    if st.session_state.get("active_model") == selected_model:
        return
    engine.adapter.model = selected_model
    st.session_state.active_model = selected_model
    set_notice(f"Model changed to '{selected_model}'. The next request will use it.")


def get_story_engine() -> StoryEngine:
    return st.session_state.orchestrator


def build_sidebar(world_defaults: WorldModel) -> tuple[SessionConfig, DisplayOptions, bool]:
    with st.sidebar:
        st.title("Session")

        model_choices = get_model_choices()
        selected_model = st.session_state.get("model_input", get_ollama_default_model())
        if selected_model not in model_choices:
            model_choices = [selected_model, *model_choices]

        model = st.selectbox(
            "Model",
            options=model_choices,
            index=model_choices.index(selected_model),
            key="model_input",
        )

        default_roll_mode = get_roll_mode()
        roll_mode = st.radio(
            "Roll handling",
            options=["auto", "manual"],
            index=0 if st.session_state.get("roll_mode_input", default_roll_mode) == "auto" else 1,
            key="roll_mode_input",
            horizontal=True,
        )

        with st.expander("Story Setup", expanded=False):
            starting_location = st.text_input(
                "Starting location",
                value=st.session_state.get(
                    "starting_location_input",
                    world_defaults.starting_location,
                ),
                key="starting_location_input",
            )
            starting_state = st.text_area(
                "Starting state",
                value=st.session_state.get(
                    "starting_state_input",
                    world_defaults.starting_state,
                ),
                height=180,
                key="starting_state_input",
            )

        reset_requested = st.button("Reset Session With Current Setup", use_container_width=True)
        st.caption("Model changes apply on the next request. Story setup changes apply only after reset.")

        st.divider()
        show_debug_trace = st.checkbox("Show raw debug trace", value=False)

    config = SessionConfig(
        model=str(model or "").strip(),
        starting_location=str(starting_location or "").strip(),
        starting_state=str(starting_state or "").strip(),
        roll_mode=str(roll_mode or "auto").strip().lower(),
    )
    display = DisplayOptions(show_debug_trace=show_debug_trace)
    return config, display, reset_requested


def append_message(role: str, content: str) -> None:
    st.session_state.messages.append({"role": role, "content": content})


def set_notice(message: str) -> None:
    st.session_state.ui_notice = str(message or "").strip()


def render_notice() -> None:
    message = str(st.session_state.get("ui_notice") or "").strip()
    if not message:
        return
    st.success(message)
    st.session_state.ui_notice = ""


def is_waiting_for_roll() -> bool:
    return bool(
        st.session_state.get("awaiting_manual_roll")
        and st.session_state.get("pending_player_input")
    )


def run_turn_with_ui(engine: StoryEngine, player_input: str, *, spinner_text: str) -> None:
    with st.spinner(spinner_text):
        try:
            turn = engine.run_turn(player_input)
        except Exception as exc:
            if ROLL_REQUIRED_SENTINEL in str(exc):
                st.rerun()
            clear_manual_roll_state(clear_pending_input=True)
            append_message("assistant", ENGINE_ERROR_MESSAGE)
            st.error(f"Turn failed: {exc}")
            st.rerun()

    st.session_state.last_turn = turn
    clear_manual_roll_state(clear_pending_input=True)
    append_message("assistant", str(turn.get("narration", {}).get("ic") or "").strip())
    st.rerun()


def maybe_resume_pending_turn(engine: StoryEngine) -> None:
    pending_input = st.session_state.get("pending_player_input")
    captured_roll = st.session_state.get("captured_manual_roll")
    if not pending_input or captured_roll is None:
        return
    run_turn_with_ui(engine, str(pending_input), spinner_text="Applying manual roll...")


def submit_player_input(engine: StoryEngine, player_input: str, *, roll_mode: str) -> None:
    cleaned = player_input.strip()
    if not cleaned:
        return

    append_message("user", cleaned)
    if roll_mode == "manual":
        st.session_state.pending_player_input = cleaned
        st.session_state.latched_manual_roll = None

    run_turn_with_ui(engine, cleaned, spinner_text="The Dungeon Master is thinking...")


def format_list(values: list[str], *, exclude_player: bool = False) -> str:
    cleaned: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item:
            continue
        if exclude_player and item.lower() == "player":
            continue
        cleaned.append(item)
    return ", ".join(cleaned) or "None"


def format_lines(values: list[str]) -> str:
    return "\n".join(str(value).strip() for value in values if str(value).strip())


def parse_text_lines(text: str) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for raw_line in str(text or "").splitlines():
        item = raw_line.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        lines.append(item)
    return lines


def parse_token_list(text: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    normalized = str(text or "").replace(",", "\n")
    for raw_line in normalized.splitlines():
        item = raw_line.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        tokens.append(item)
    return tokens


def format_json(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True)


def parse_json_mapping(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object.")
    return {str(key): value for key, value in payload.items()}


def parse_int_mapping(text: str) -> dict[str, int]:
    payload = parse_json_mapping(text)
    result: dict[str, int] = {}
    for key, value in payload.items():
        try:
            result[str(key)] = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Value for '{key}' must be an integer.") from exc
    return result


def parse_bool_mapping(text: str) -> dict[str, bool]:
    payload = parse_json_mapping(text)
    result: dict[str, bool] = {}
    for key, value in payload.items():
        if isinstance(value, bool):
            result[str(key)] = value
            continue
        if isinstance(value, (int, float)):
            result[str(key)] = bool(value)
            continue
        normalized = str(value).strip().lower()
        if normalized in {"true", "1", "yes"}:
            result[str(key)] = True
            continue
        if normalized in {"false", "0", "no"}:
            result[str(key)] = False
            continue
        raise ValueError(f"Value for '{key}' must be a boolean.")
    return result


def sorted_location_keys(engine: StoryEngine) -> list[str]:
    return [location.key for location in sorted(engine.world.locations.values(), key=lambda value: value.key.lower())]


def sorted_entity_keys(engine: StoryEngine) -> list[str]:
    return [entity.key for entity in sorted(engine.world.entities.values(), key=lambda value: value.key.lower())]


def sorted_item_keys(engine: StoryEngine) -> list[str]:
    return [item.key for item in sorted(engine.world.items.values(), key=lambda value: value.key.lower())]


def collect_memory_rows(engine: StoryEngine, entity_key: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    selected_key = str(entity_key or "").strip().lower()
    for key in sorted_entity_keys(engine):
        entity = engine.world.get_entity(key)
        if entity is None:
            continue
        if selected_key and entity.key.lower() != selected_key:
            continue
        for index, sentence in enumerate(entity.memory.sentences, start=1):
            rows.append(
                {
                    "entity": entity.key,
                    "entity_type": entity.entity_type,
                    "memory_index": index,
                    "sentence": sentence,
                }
            )
    return rows


def search_memory_rows(engine: StoryEngine, scope: str, query: str, top_n: int) -> list[dict[str, Any]]:
    cleaned_query = str(query or "").strip()
    if not cleaned_query:
        return []

    scope_key = str(scope or "").strip()
    rows: list[dict[str, Any]] = []
    if scope_key == "__all__":
        for entity_key in sorted_entity_keys(engine):
            result = retrieve_memory_tool(
                entity_name=entity_key,
                context=cleaned_query,
                top_n=max(1, int(top_n)),
                game_state=engine.game_state,
            )
            for hit in result.get("memories", []):
                rows.append(
                    {
                        "entity": entity_key,
                        "score": float(hit.get("score", 0.0)),
                        "sentence": str(hit.get("sentence") or ""),
                    }
                )
        rows.sort(key=lambda row: (float(row["score"]), str(row["entity"])), reverse=True)
        return rows[: max(1, int(top_n))]

    result = retrieve_memory_tool(
        entity_name=scope_key,
        context=cleaned_query,
        top_n=max(1, int(top_n)),
        game_state=engine.game_state,
    )
    for hit in result.get("memories", []):
        rows.append(
            {
                "entity": scope_key,
                "score": float(hit.get("score", 0.0)),
                "sentence": str(hit.get("sentence") or ""),
            }
        )
    return rows


def sync_npc_locations(engine: StoryEngine) -> None:
    engine.game_state.npc_locations.clear()
    for entity in engine.world.entities.values():
        if entity.entity_type == "npc" and entity.location:
            engine.game_state.npc_locations[entity.key] = entity.location


def sync_player_location(engine: StoryEngine, location_key: str) -> None:
    engine.game_state.player_location = str(location_key or "").strip()
    engine.game_state.discovered_keys.add(engine.game_state.player_location)
    engine.discovered_keys = engine.game_state.discovered_keys
    player = engine.world.get_entity("Player")
    if player is not None:
        player.set_location(engine.game_state.player_location)


def build_world_state_dot(snapshot: dict[str, Any]) -> str:
    nodes = snapshot.get("nodes") or []
    edges = snapshot.get("edges") or []

    lines = [
        "graph WorldState {",
        '  graph [bgcolor="transparent", splines=true, overlap=false];',
        '  node [shape=ellipse, style=filled, fontname="Helvetica", fontsize=11, color="#6b7280"];',
        '  edge [color="#cbd5e1", penwidth=1.1];',
    ]

    for node in nodes:
        key = str(node.get("key") or "").strip()
        if not key:
            continue
        escaped_key = key.replace("\\", "\\\\").replace('"', '\\"')
        flags = node.get("flags") or {}
        if flags.get("current_location"):
            fill = "#dbeafe"
            color = "#2563eb"
        elif flags.get("in_scene"):
            fill = "#f3f4f6"
            color = "#6b7280"
        else:
            fill = "#ffffff"
            color = "#9ca3af"
        lines.append(f'  "{escaped_key}" [fillcolor="{fill}", color="{color}"];')

    for edge in edges:
        src = str(edge.get("src") or "").strip()
        dst = str(edge.get("dst") or "").strip()
        if not src or not dst:
            continue
        escaped_src = src.replace("\\", "\\\\").replace('"', '\\"')
        escaped_dst = dst.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'  "{escaped_src}" -- "{escaped_dst}";')

    lines.append("}")
    return "\n".join(lines)


def render_roll_panel() -> None:
    if not is_waiting_for_roll():
        return

    roll_request = dict(st.session_state.get("roll_request") or {})
    notation = str(roll_request.get("notation") or "1d20")
    max_face = int(roll_request.get("max_face") or 20)
    pending_input = str(st.session_state.get("pending_player_input") or "").strip()

    st.subheader("Manual Roll")
    st.info(f"Enter the result for `{notation}` to continue this turn.")
    st.caption(f"Pending action: {pending_input}")

    with st.form("manual_roll_form"):
        roll_value = st.number_input(
            "Roll result",
            min_value=1,
            max_value=max_face,
            value=1,
            step=1,
        )
        submitted = st.form_submit_button("Apply Roll", use_container_width=True)

    if submitted:
        st.session_state.captured_manual_roll = int(roll_value)
        st.rerun()


def render_messages() -> None:
    st.subheader("Conversation")
    for message in st.session_state.get("messages", []):
        with st.chat_message(str(message.get("role") or "assistant")):
            st.markdown(str(message.get("content") or ""))


def render_overview(snapshot: dict[str, Any]) -> None:
    beat = snapshot.get("beat_state") or {}
    total = int(beat.get("total", 0))
    beat_progress = f"{int(beat.get('current_index', 0)) + 1} of {total}" if total else "Not started"

    st.subheader("Engine State")
    st.markdown(f"**Turn:** {snapshot.get('turn', 0)}")
    st.markdown(f"**Location:** {snapshot.get('current_location') or 'Unknown'}")
    st.markdown(f"**Beat:** {beat_progress}")
    st.write(str(beat.get("current") or "No active beat."))


def render_scene(snapshot: dict[str, Any]) -> None:
    scene = snapshot.get("scene") or {}
    st.subheader("Current Scene")
    st.write(str(scene.get("description") or "No scene description available."))
    st.markdown(f"**Connections:** {format_list(scene.get('connections') or [])}")
    st.markdown(f"**Actors Here:** {format_list(scene.get('actors_here') or [], exclude_player=True)}")
    st.markdown(f"**Items Here:** {format_list(scene.get('items_here') or [])}")


def render_story_state(snapshot: dict[str, Any]) -> None:
    story_status = str(snapshot.get("story_status") or "").strip()
    session_summary = str(snapshot.get("session_summary") or "").strip()

    if story_status:
        st.subheader("Story Status")
        st.write(story_status)

    if session_summary:
        st.subheader("Session Summary")
        st.text(session_summary)


def render_last_turn() -> None:
    last_turn = st.session_state.get("last_turn") or {}
    if not last_turn:
        return

    phase_summaries = last_turn.get("phase_summaries") or {}
    tool_calls = last_turn.get("tool_calls") or []
    turn_todo = last_turn.get("turn_todo") or []

    with st.expander("Last Turn Details", expanded=False):
        if phase_summaries:
            st.markdown("**Phase Summaries**")
            st.json(phase_summaries, expanded=False)
        if tool_calls:
            st.markdown("**Tool Calls**")
            st.json(tool_calls, expanded=False)
        if turn_todo:
            st.markdown("**Turn Todo**")
            st.json(turn_todo, expanded=False)


def render_world_graph(snapshot: dict[str, Any]) -> None:
    nodes = snapshot.get("nodes") or []
    if not nodes:
        return

    with st.expander("World Graph", expanded=False):
        st.graphviz_chart(build_world_state_dot(snapshot), use_container_width=True)


def render_debug_trace(display: DisplayOptions) -> None:
    if not display.show_debug_trace:
        return

    last_turn = st.session_state.get("last_turn") or {}
    debug_data = last_turn.get("llm_trace") or last_turn.get("llm_debug")
    with st.expander("Raw Debug Trace", expanded=False):
        if debug_data:
            st.json(debug_data, expanded=False)
        else:
            st.write("No debug trace is available yet.")


def render_runtime_editor(engine: StoryEngine) -> None:
    st.subheader("Runtime State")
    st.caption("These changes affect the live session only.")

    location_keys = sorted_location_keys(engine)
    if not location_keys:
        st.info("No locations are available in the current world model.")
        return
    current_location = engine.game_state.player_location
    if current_location not in location_keys and current_location:
        location_keys = [current_location, *location_keys]

    beat_options = list(range(len(engine.beats.beats)))
    current_beat_index = engine.beats.index if beat_options else 0
    if beat_options:
        current_beat_index = max(0, min(current_beat_index, len(beat_options) - 1))

    with st.form("runtime_state_editor_form"):
        player_location = st.selectbox(
            "Player location",
            options=location_keys,
            index=location_keys.index(current_location) if current_location in location_keys else 0,
        )
        story_status = st.text_area("Story status", value=engine.story_status, height=140)
        session_summary = st.text_area(
            "Session summary lines",
            value=format_lines(engine.summary.events),
            height=140,
            help="One summary event per line.",
        )
        discovered_keys_text = st.text_area(
            "Discovered keys",
            value=format_lines(sorted(engine.game_state.discovered_keys)),
            height=140,
            help="One key per line.",
        )
        quest_flags_text = st.text_area(
            "Quest flags (JSON)",
            value=format_json(engine.game_state.quest_flags),
            height=180,
        )
        if beat_options:
            beat_index = st.selectbox(
                "Current beat",
                options=beat_options,
                index=current_beat_index,
                format_func=lambda idx: f"{idx + 1}. {engine.beats.beats[idx]}",
            )
        else:
            beat_index = None
            st.write("No beats are configured for this session.")
        submitted = st.form_submit_button("Apply Runtime Changes", use_container_width=True)

    if not submitted:
        return

    try:
        quest_flags = parse_bool_mapping(quest_flags_text)
    except ValueError as exc:
        st.error(str(exc))
        return

    discovered_keys = set(parse_token_list(discovered_keys_text))
    discovered_keys.add(player_location)
    engine.game_state.discovered_keys.clear()
    engine.game_state.discovered_keys.update(discovered_keys)
    sync_player_location(engine, player_location)
    engine.story_status = story_status.strip()
    engine.summary.events = parse_text_lines(session_summary)
    engine.game_state.quest_flags.clear()
    engine.game_state.quest_flags.update(quest_flags)
    if beat_index is not None:
        engine.beats.index = int(beat_index)
    sync_npc_locations(engine)
    set_notice("Runtime state updated.")
    st.rerun()


def render_location_editor(engine: StoryEngine) -> None:
    location_keys = sorted_location_keys(engine)
    if not location_keys:
        st.info("No locations are loaded.")
        return

    st.subheader("Locations")
    selected_key = st.selectbox("Location", options=location_keys, key="location_editor_select")
    location = engine.world.get_location(selected_key)
    if location is None:
        st.error("Selected location was not found.")
        return

    form_col, preview_col = st.columns([1.4, 1], gap="large")
    with form_col:
        with st.form("location_editor_form"):
            name = st.text_input("Name", value=location.name)
            description = st.text_area("Description", value=location.description, height=180)
            connections_text = st.text_area(
                "Connections",
                value=format_lines(location.connections),
                height=140,
                help="One location key per line.",
            )
            tags_text = st.text_area(
                "Tags",
                value=format_lines(location.tags),
                height=100,
                help="One tag per line.",
            )
            submitted = st.form_submit_button("Apply Location Changes", use_container_width=True)

        if submitted:
            connections = parse_token_list(connections_text)
            unknown_connections = [key for key in connections if engine.world.get_location(key) is None]
            if unknown_connections:
                st.error(f"Unknown connected locations: {', '.join(unknown_connections)}")
            else:
                location.name = name.strip() or location.key
                location.description = description.strip()
                location.connections = connections
                location.tags = parse_token_list(tags_text)
                set_notice(f"Updated location '{location.key}'.")
                st.rerun()

    with preview_col:
        st.markdown("**Current Record**")
        st.json(location.to_record(), expanded=False)


def render_entity_editor(engine: StoryEngine) -> None:
    entity_keys = sorted_entity_keys(engine)
    if not entity_keys:
        st.info("No entities are loaded.")
        return

    st.subheader("Entities")
    selected_key = st.selectbox("Entity", options=entity_keys, key="entity_editor_select")
    entity = engine.world.get_entity(selected_key)
    if entity is None:
        st.error("Selected entity was not found.")
        return

    entity_type_options = sorted({"npc", "player", *[value.entity_type for value in engine.world.entities.values()]})
    if entity.entity_type not in entity_type_options:
        entity_type_options.append(entity.entity_type)

    location_keys = sorted_location_keys(engine)
    if not location_keys:
        st.error("No locations are available, so entity locations cannot be edited.")
        return
    current_location = entity.location
    if current_location not in location_keys and current_location:
        location_keys = [current_location, *location_keys]

    form_col, preview_col = st.columns([1.4, 1], gap="large")
    with form_col:
        with st.form("entity_editor_form"):
            name = st.text_input("Name", value=entity.name)
            entity_type = st.selectbox(
                "Entity type",
                options=entity_type_options,
                index=entity_type_options.index(entity.entity_type),
            )
            location = st.selectbox(
                "Location",
                options=location_keys,
                index=location_keys.index(current_location) if current_location in location_keys else 0,
            )
            description = st.text_area("Description", value=entity.description, height=160)
            tags_text = st.text_area(
                "Tags",
                value=format_lines(entity.tags),
                height=100,
                help="One tag per line.",
            )
            skills_text = st.text_area("Skills (JSON)", value=format_json(entity.skills), height=160)
            stats_text = st.text_area("Stats (JSON)", value=format_json(entity.stats), height=160)
            memory_text = st.text_area(
                "Memory lines",
                value=format_lines(entity.memory.sentences),
                height=140,
                help="One memory line per line.",
            )
            submitted = st.form_submit_button("Apply Entity Changes", use_container_width=True)

        if submitted:
            try:
                skills = parse_int_mapping(skills_text)
                stats = parse_int_mapping(stats_text)
            except ValueError as exc:
                st.error(str(exc))
            else:
                entity.name = name.strip() or entity.key
                entity.entity_type = entity_type.strip().lower() or entity.entity_type
                entity.set_location(location)
                entity.description = description.strip()
                entity.tags = parse_token_list(tags_text)
                entity.skills = skills
                entity.stats = stats
                entity.memory.sentences = parse_text_lines(memory_text)
                engine.world.sync_actor_inventories()
                sync_npc_locations(engine)
                if entity.key.lower() == "player" or entity.entity_type == "player":
                    sync_player_location(engine, location)
                set_notice(f"Updated entity '{entity.key}'.")
                st.rerun()

    with preview_col:
        st.markdown("**Current Record**")
        st.json(entity.to_public_view(include_memory_preview=True), expanded=False)


def render_item_editor(engine: StoryEngine) -> None:
    item_keys = sorted_item_keys(engine)
    if not item_keys:
        st.info("No items are loaded.")
        return

    st.subheader("Items")
    selected_key = st.selectbox("Item", options=item_keys, key="item_editor_select")
    item = engine.world.get_item(selected_key)
    if item is None:
        st.error("Selected item was not found.")
        return

    holder_kind_options = ["location", "entity"]
    current_holder_kind = item.holder_kind if item.holder_kind in holder_kind_options else "location"
    selected_holder_kind = st.selectbox(
        "Holder type",
        options=holder_kind_options,
        index=holder_kind_options.index(current_holder_kind),
        key="item_editor_holder_kind",
    )
    holder_options = (
        sorted_location_keys(engine)
        if selected_holder_kind == "location"
        else sorted_entity_keys(engine)
    )
    current_holder_key = item.holder_key
    if current_holder_key not in holder_options and current_holder_key:
        holder_options = [current_holder_key, *holder_options]
    if not holder_options:
        st.error(f"No valid {selected_holder_kind} holders are available for this item.")
        return

    form_col, preview_col = st.columns([1.4, 1], gap="large")
    with form_col:
        with st.form("item_editor_form"):
            name = st.text_input("Name", value=item.name)
            description = st.text_area("Description", value=item.description, height=160)
            holder_key = st.selectbox(
                "Holder",
                options=holder_options,
                index=holder_options.index(current_holder_key) if current_holder_key in holder_options else 0,
            )
            portable = st.checkbox("Portable", value=bool(item.portable))
            tags_text = st.text_area(
                "Tags",
                value=format_lines(item.tags),
                height=100,
                help="One tag per line.",
            )
            submitted = st.form_submit_button("Apply Item Changes", use_container_width=True)

        if submitted:
            item.name = name.strip() or item.key
            item.description = description.strip()
            item.set_holder(selected_holder_kind, holder_key)
            item.portable = bool(portable)
            item.tags = parse_token_list(tags_text)
            engine.world.sync_actor_inventories()
            set_notice(f"Updated item '{item.key}'.")
            st.rerun()

    with preview_col:
        st.markdown("**Current Record**")
        st.json(item.to_record(), expanded=False)


def render_memory_browser(engine: StoryEngine) -> None:
    entity_keys = sorted_entity_keys(engine)
    if not entity_keys:
        st.info("No entities are loaded, so no runtime memory is available.")
        return

    backend_status = DynamicSentenceMemory.backend_status()
    memory_rows = collect_memory_rows(engine)
    entities_with_memory = len({row["entity"] for row in memory_rows})

    st.subheader("Memory RAG")
    st.caption("This is the live runtime memory store and retrieval path used by the session.")

    metric_col_1, metric_col_2, metric_col_3 = st.columns(3)
    with metric_col_1:
        st.metric("Entities", len(entity_keys))
    with metric_col_2:
        st.metric("With Memory", entities_with_memory)
    with metric_col_3:
        st.metric("Memory Rows", len(memory_rows))

    st.markdown("**Backend Status**")
    st.json(backend_status, expanded=False)

    query_tab, corpus_tab = st.tabs(["Query", "Corpus"])

    with query_tab:
        scope_options = ["__all__", *entity_keys]
        scope = st.selectbox(
            "Scope",
            options=scope_options,
            format_func=lambda value: "All entities" if value == "__all__" else value,
            key="memory_query_scope",
        )
        query = st.text_input(
            "Query",
            value=st.session_state.get("memory_query_text", ""),
            key="memory_query_text",
            placeholder="Search the runtime memories for a clue, person, or event...",
        )
        top_n = st.slider("Top results", min_value=1, max_value=10, value=4, key="memory_query_top_n")

        if not query.strip():
            st.info("Enter a query to inspect memory retrieval results.")
        else:
            results = search_memory_rows(engine, scope=scope, query=query, top_n=top_n)
            if results:
                st.dataframe(results, use_container_width=True)
            else:
                st.write("No memory hits matched this query.")

            if scope != "__all__":
                tool_payload = retrieve_memory_tool(
                    entity_name=scope,
                    context=query,
                    top_n=top_n,
                    game_state=engine.game_state,
                )
                with st.expander("Tool Payload", expanded=False):
                    st.json(tool_payload, expanded=False)

    with corpus_tab:
        selected_entity = st.selectbox(
            "Entity",
            options=["__all__", *entity_keys],
            format_func=lambda value: "All entities" if value == "__all__" else value,
            key="memory_corpus_entity",
        )

        if selected_entity == "__all__":
            st.dataframe(memory_rows, use_container_width=True)
        else:
            entity_rows = collect_memory_rows(engine, entity_key=selected_entity)
            if entity_rows:
                st.dataframe(entity_rows, use_container_width=True)
            else:
                st.write("This entity has no stored memory rows.")


def render_snapshot_browser(engine: StoryEngine, display: DisplayOptions) -> None:
    snapshot = engine.snapshot()
    validation_errors = engine.world.validate()

    if validation_errors:
        st.warning("\n".join(validation_errors))
    else:
        st.success("World model validation passed.")

    st.subheader("Browse")
    browse_tab, snapshot_tab = st.tabs(["Records", "Snapshot"])

    with browse_tab:
        st.markdown("**Story Record**")
        st.json(engine.world.story_record(), expanded=False)
        st.markdown("**Locations**")
        st.dataframe(engine.world.list_location_records(), use_container_width=True)
        st.markdown("**Entities**")
        entity_rows = [engine.world.get_entity(key).to_public_view() for key in sorted_entity_keys(engine)]
        st.dataframe(entity_rows, use_container_width=True)
        st.markdown("**Items**")
        st.dataframe(engine.world.list_item_records(), use_container_width=True)

    with snapshot_tab:
        st.markdown("**Runtime Snapshot**")
        st.json(snapshot, expanded=False)
        render_world_graph(snapshot)
        render_debug_trace(display)


def render_world_state_editor(engine: StoryEngine, display: DisplayOptions) -> None:
    st.caption("Inspect and edit the current in-memory world state for this session.")
    runtime_tab, location_tab, entity_tab, item_tab, memory_tab, snapshot_tab = st.tabs(
        ["Runtime", "Locations", "Entities", "Items", "Memory", "Browse"]
    )

    with runtime_tab:
        render_runtime_editor(engine)
    with location_tab:
        render_location_editor(engine)
    with entity_tab:
        render_entity_editor(engine)
    with item_tab:
        render_item_editor(engine)
    with memory_tab:
        render_memory_browser(engine)
    with snapshot_tab:
        render_snapshot_browser(engine, display)


def main() -> None:
    st.set_page_config(page_title="Dungeon Master's Companion", layout="wide")
    ensure_runtime_state()

    world_defaults = load_world_defaults()
    session_config, display, reset_requested = build_sidebar(world_defaults)
    ensure_session(session_config, reset_requested=reset_requested)

    engine = get_story_engine()
    sync_engine_model(engine, session_config.model)
    try:
        engine.adapter.verbose = bool(display.show_debug_trace)
    except Exception:
        pass

    maybe_resume_pending_turn(engine)

    st.title("Dungeon Master's Companion")
    st.caption("A plain Streamlit interface for the story engine and its current world state.")
    render_notice()
    if st.session_state.get("config_signature") != session_config.reset_signature():
        st.info("Story setup changes are staged. Reset the session to apply them.")

    play_tab, editor_tab = st.tabs(["Play", "World State"])

    with play_tab:
        chat_col, state_col = st.columns([2, 1], gap="large")

        with chat_col:
            render_messages()
            render_roll_panel()

            player_input = st.chat_input(
                "Describe what your character does...",
                disabled=is_waiting_for_roll(),
            )
            if player_input:
                submit_player_input(engine, player_input, roll_mode=session_config.roll_mode)

        with state_col:
            snapshot = engine.snapshot()
            render_overview(snapshot)
            render_scene(snapshot)
            render_story_state(snapshot)
            render_last_turn()
            render_world_graph(snapshot)
            render_debug_trace(display)

    with editor_tab:
        render_world_state_editor(engine, display)


if __name__ == "__main__":
    main()

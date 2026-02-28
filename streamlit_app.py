from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st

from orchestrator.app_config import get_ollama_default_model
from orchestrator.runtime_flow.pipeline import StoryEngine
from orchestrator.world_state.world_model import build_world_model

###
PLAYER_BG_PATH = Path("UI-Assets/town-square.jpg")
APP_BG_PATH = Path("UI-Assets/FantasyPort.jpg")


def _default_world_model():
    return build_world_model()


def _config_signature(model: str, starting_location: str, starting_state: str) -> str:
    return f"{model}|{starting_location}|{starting_state}"


def _initialize_session(model: str, starting_location: str, starting_state: str) -> None:
    engine = StoryEngine(
        model=model,
        starting_location=starting_location,
        starting_state=starting_state,
    )
    messages: List[Dict[str, str]] = []
    intro_text = starting_state
    try:
        intro = engine.generate_intro()
        intro_text = intro.get("ic") or starting_state
    except Exception as exc:
        st.warning("Intro generation failed; showing the starting state instead.")
        st.exception(exc)
    messages.append({"role": "assistant", "content": intro_text})

    st.session_state.orchestrator = engine
    st.session_state.messages = messages
    st.session_state.last_turn = {}
    st.session_state.config_sig = _config_signature(model, starting_location, starting_state)


def _get_story_engine() -> StoryEngine:
    return st.session_state.orchestrator


def _inject_player_background(image_path: Path) -> None:
    try:
        data = image_path.read_bytes()
    except OSError:
        st.sidebar.warning(f"Player background image not found at {image_path.as_posix()}")
        return

    suffix = image_path.suffix.lower()
    mime = "image/jpeg"
    if suffix == ".png":
        mime = "image/png"
    elif suffix == ".webp":
        mime = "image/webp"

    encoded = base64.b64encode(data).decode("ascii")
    st.markdown(
        f"""
        <style>
          @import url('https://fonts.googleapis.com/css2?family=Tangerine:wght@400;700&display=swap');

          :root {{
            --player-bg: url("data:{mime};base64,{encoded}");
          }}

          .block-container {{
            max-width: 1600px;
            padding-left: 2.25rem;
            padding-right: 2.25rem;
          }}

          .tangerine-regular {{
            font-family: "Tangerine", cursive;
            font-weight: 400;
            font-style: normal;
          }}

          .tangerine-bold {{
            font-family: "Tangerine", cursive;
            font-weight: 700;
            font-style: normal;
          }}

          .hero-caption {{
            text-align: center;
            margin-top: -0.35rem;
            margin-bottom: 1.25rem;
            color: rgba(243, 239, 230, 0.8);
          }}

          [data-testid="stTabs"] [role="tablist"] {{
            justify-content: center;
          }}

          [data-testid="stChatMessage"] {{
            background: rgba(8, 10, 14, 0.55);
            border-radius: 12px;
            padding: 0.15rem 0.85rem;
          }}

          div[data-testid="stVerticalBlock"]:has(#character-image-anchor) {{
            position: relative;
          }}

          div[data-testid="stVerticalBlock"]:has(#character-image-anchor)
            div[data-testid="stElementContainer"]:has(#character-image-anchor) {{
            display: none;
          }}

          div[data-testid="stVerticalBlock"]:has(#character-image-anchor)
            div[data-testid="stElementContainer"]:has(#character-image-anchor)
            + div[data-testid="stElementContainer"] {{
            position: absolute;
            top: 0.6rem;
            right: 0.6rem;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.2s ease;
            z-index: 5;
          }}

          div[data-testid="stVerticalBlock"]:has(#character-image-anchor):has(div[data-testid="stImage"]:hover)
            div[data-testid="stElementContainer"]:has(#character-image-anchor)
            + div[data-testid="stElementContainer"],
          div[data-testid="stVerticalBlock"]:has(#character-image-anchor):has(div[data-testid="stButton"]:hover)
            div[data-testid="stElementContainer"]:has(#character-image-anchor)
            + div[data-testid="stElementContainer"] {{
            opacity: 1;
            pointer-events: auto;
            transition-delay: 0.2s;
          }}

          div[data-testid="stVerticalBlock"]:has(#character-image-anchor)
            div[data-testid="stElementContainer"]:has(#character-image-anchor)
            + div[data-testid="stElementContainer"] > div[data-testid="stButton"] > button {{
            white-space: nowrap;
            padding: 0.35rem 0.7rem;
            min-width: 0;
            width: auto;
            font-size: 0.8rem;
            line-height: 1.1;
            border-radius: 999px;
            background: rgba(9, 12, 18, 0.85);
            border: 1px solid rgba(255, 255, 255, 0.2);
            color: #f3efe6;
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.35);
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _inject_app_background(image_path: Path) -> None:
    try:
        data = image_path.read_bytes()
    except OSError:
        st.warning(f"App background image not found at {image_path.as_posix()}")
        return

    suffix = image_path.suffix.lower()
    mime = "image/jpeg"
    if suffix == ".png":
        mime = "image/png"
    elif suffix == ".webp":
        mime = "image/webp"

    encoded = base64.b64encode(data).decode("ascii")
    st.markdown(
        f"""
        <style>
          :root {{
            --app-bg: url("data:{mime};base64,{encoded}");
          }}

          body,
          .stApp,
          div[data-testid="stAppViewContainer"] {{
            background-image: var(--app-bg);
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _dot_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _build_world_state_dot(snapshot: Dict[str, Any]) -> str:
    nodes = snapshot.get("nodes") or []
    edges = snapshot.get("edges") or []
    active = set(snapshot.get("active_keys") or [])
    focus = set(snapshot.get("focus") or [])

    lines = [
        "graph WorldState {",
        '  graph [bgcolor="transparent", splines=true, overlap=false];',
        '  node [shape=ellipse, style=filled, fontname="Helvetica", fontsize=11, color="#2f3a45"];',
        '  edge [color="#98a1ab", penwidth=1.2];',
    ]

    for node in nodes:
        key = str(node.get("key", "")).strip()
        if not key:
            continue
        label = _dot_escape(key)
        if key in focus:
            fill = "#f4d35e"
            font = "#1f2328"
            pen = "#b08900"
            penwidth = 2.4
        elif key in active:
            fill = "#61c9a8"
            font = "#0b1a15"
            pen = "#2f7f64"
            penwidth = 2.0
        else:
            fill = "#c8ced6"
            font = "#1f2328"
            pen = "#7b8794"
            penwidth = 1.2
        lines.append(
            f'  "{label}" [fillcolor="{fill}", fontcolor="{font}", color="{pen}", penwidth={penwidth}];'
        )

    for edge in edges:
        src = str(edge.get("src", "")).strip()
        dst = str(edge.get("dst", "")).strip()
        if not src or not dst:
            continue
        lines.append(f'  "{_dot_escape(src)}" -- "{_dot_escape(dst)}";')

    lines.append("}")
    return "\n".join(lines)


def main() -> None:
    st.set_page_config(page_title="The Dungeon Master's Companion", layout="wide")
    world_defaults = _default_world_model()
    st.markdown(
        '<h1 class="tangerine-bold" '
        'style="font-size:70px; text-align:center; margin-bottom:0.25rem; font-family:\'Tangerine\', cursive;">'
        "The Dungeon Master's Companion</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="hero-caption">Describe your character\'s actions. The Dungeon Master responds and advances the story.</div>',
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.header("Session")
        model = st.text_input(
            "Ollama model",
            value=st.session_state.get("model_input", get_ollama_default_model()),
            key="model_input",
        ) or ""

        starting_location = st.text_input(
            "Starting location",
            value=st.session_state.get("starting_location_input", world_defaults.starting_location),
            key="starting_location_input",
        ) or ""

        starting_state = st.text_area(
            "Starting state",
            value=st.session_state.get("starting_state_input", world_defaults.starting_state),
            height=200,
            key="starting_state_input",
        ) or ""

        start_new = st.button("Start new session")
        show_status = st.checkbox("Show story status", value=True)
        show_debug = st.checkbox("Show debug info", value=False)

    sig = _config_signature(model, starting_location, starting_state)

    if "orchestrator" not in st.session_state:
        _initialize_session(model, starting_location, starting_state)
    elif start_new or st.session_state.get("config_sig") != sig:
        _initialize_session(model, starting_location, starting_state)

    _inject_player_background(PLAYER_BG_PATH)
    _inject_app_background(APP_BG_PATH)

    engine = _get_story_engine()

    play_tab, dm_tab = st.tabs(["Player View", "DM Tools"])

    with play_tab:
        st.markdown('<div id="play-layout-anchor"></div>', unsafe_allow_html=True)
        spacer_col, chat_col, character_col = st.columns([1, 2.4, 1], gap="large")

        with chat_col:
            st.image(PLAYER_BG_PATH, use_container_width=True)
            messages_container = st.container()
            with messages_container:
                for message in st.session_state.get("messages", []):
                    with st.chat_message(message["role"]):
                        st.markdown(message["content"])

            with st.form("chat_form", clear_on_submit=True):
                player_input = st.text_area(
                    "Describe what your character does...",
                    height=90,
                    label_visibility="collapsed",
                )
                submitted = st.form_submit_button("Send")

            if submitted and player_input.strip():
                st.session_state.messages.append({"role": "user", "content": player_input})
                with st.spinner("The Dungeon Master is thinking..."):
                    try:
                        turn = engine.run_turn(player_input)
                        response = turn["narration"]["ic"]
                        st.session_state.last_turn = turn
                    except Exception as exc:
                        response = "The Dungeon Master is unavailable right now."
                        st.error(f"Failed to generate a response: {exc}")
                st.session_state.messages.append({"role": "assistant", "content": response})
                st.rerun()

        with character_col:
            st.subheader("Character")
            image_container = st.container()
            with image_container:
                character_image = st.session_state.get("character_image_upload")
                if character_image is None:
                    character_image = st.file_uploader(
                    "Character image",
                    type=["png", "jpg", "jpeg", "webp"],
                    key="character_image_upload",
                )
                if character_image:
                    st.markdown('<div id="character-image-anchor"></div>', unsafe_allow_html=True)
                    if st.button("Reupload image", key="character_image_reupload"):
                        st.session_state.character_image_upload = None
                        st.rerun()
                    st.image(character_image, use_container_width=True)

            description_default = st.session_state.get("character_description", "")
            description = st.text_area(
                "Character description",
                value=description_default,
                height=160,
                key="character_description",
            )
            inventory_default = st.session_state.get("character_inventory", "")
            st.text_area(
                "Inventory",
                value=inventory_default,
                height=140,
                placeholder="One item per line",
                key="character_inventory",
            )
            stats_default = st.session_state.get("character_stats", "")
            st.text_area(
                "Character stats",
                value=stats_default,
                height=140,
                placeholder="e.g., STR 14, DEX 12, CON 13",
                key="character_stats",
            )

    with dm_tab:
        snapshot = engine.snapshot()
        st.subheader("Campaign Status")
        if show_status:
            beat = snapshot.get("beat_state", {})
            st.markdown(
                f"**Beat:** {beat.get('current_index', 0) + 1} "
                f"of {beat.get('total', 0)} - {beat.get('current', '')}"
            )
            st.markdown(f"**Focus:** {', '.join(snapshot.get('focus') or []) or 'None'}")
            st.markdown(f"**Active keys:** {', '.join(snapshot.get('active_keys') or []) or 'None'}")
            st.markdown(f"**Story status:** {snapshot.get('story_status') or 'Not set'}")
            summary = snapshot.get("session_summary") or ""
            if summary:
                st.text_area("Session summary", value=summary, height=160)
        else:
            st.markdown("Story status display is disabled in the sidebar.")

        st.subheader("World State")
        if snapshot.get("nodes"):
            graph_dot = _build_world_state_dot(snapshot)
            st.graphviz_chart(graph_dot, use_container_width=True)
            st.caption("Gold = focus. Teal = active. Gray = inactive.")
        else:
            st.markdown("No world-state data yet.")

        if show_debug:
            debug_data = st.session_state.get("last_turn", {}).get("llm_debug")
            with st.expander("Debug", expanded=False):
                if debug_data:
                    for step, payload in debug_data.items():
                        st.markdown(f"**{step}**")
                        st.text_area(f"{step} prompt", value=payload.get("prompt", ""), height=120)
                        st.text_area(f"{step} raw", value=payload.get("raw", ""), height=120)
                else:
                    st.markdown("No debug info available yet.")


if __name__ == "__main__":
    main()

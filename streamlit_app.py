from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from orchestrator.app_config import (
    get_default_model,
    get_default_provider,
    get_model_choices as get_provider_model_choices,
    get_ollama_default_model,
    get_ollama_model_choices,
    get_provider_names,
    get_roll_mode,
)
from orchestrator.runtime_flow.pipeline import StoryEngine
from orchestrator.runtime_flow.session_state import BeatTracker, write_session_checkpoint
from orchestrator.world_state.entity import DynamicSentenceMemory, Entity
from orchestrator.world_state.entity_tools import retrieve_memory_tool
from orchestrator.world_state.item import Item
from orchestrator.world_state.location import Location
from orchestrator.world_state.story_library import StorySource, list_story_sources
from orchestrator.world_state.tool_runtime import set_world_checkpoint_root
from orchestrator.world_state.world_model import WorldModel, build_world_model

ROLL_REQUIRED_SENTINEL = "__DMC_ROLL_REQUIRED__"
ENGINE_ERROR_MESSAGE = "The Dungeon Master is unavailable right now."


@dataclass(frozen=True)
class SessionConfig:
    provider: str
    model: str
    api_key: str
    story_key: str
    story_label: str
    world_model_data_dir: str
    starting_location: str
    starting_state: str
    roll_mode: str

    def reset_signature(self) -> str:
        return "|".join(
            [
                self.provider.strip().lower(),
                self.api_key.strip(),
                self.story_key.strip().lower(),
                self.world_model_data_dir.strip(),
                self.starting_location.strip(),
                self.starting_state.strip(),
                self.roll_mode.strip().lower(),
            ]
        )


@dataclass(frozen=True)
class DisplayOptions:
    show_debug_trace: bool


@st.cache_resource
def load_world_defaults(data_dir: str) -> WorldModel:
    return build_world_model(data_dir=data_dir)


@st.cache_data(ttl=30, show_spinner=False)
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


def get_model_choices(provider: str | None = None) -> list[str]:
    if provider and provider != "ollama":
        return list(get_provider_model_choices(provider))
    choices = get_ollama_model_choices()
    for installed_model in get_installed_ollama_models():
        if installed_model not in choices:
            choices.append(installed_model)
    return choices


def ensure_runtime_state() -> None:
    defaults = {
        "messages": [],
        "last_turn": {},
        "turn_records": [],
        "pending_player_input": None,
        "awaiting_manual_roll": False,
        "captured_manual_roll": None,
        "latched_manual_roll": None,
        "roll_request": {},
        "config_signature": "",
        "active_model": "",
        "ui_notice": "",
        "session_dir": "",
        "snapshot_files": [],
        "active_story_key": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def create_streamlit_session_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = Path("state") / f"{stamp}_streamlit_session"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir.resolve()


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
        provider=config.provider,
        model=config.model,
        api_key=config.api_key or None,
        world_model_data_dir=config.world_model_data_dir,
        starting_location=config.starting_location,
        starting_state=config.starting_state,
        roll_mode=config.roll_mode,
        manual_roll_provider=streamlit_manual_roll_provider if config.roll_mode == "manual" else None,
    )
    session_dir = create_streamlit_session_dir()
    set_world_checkpoint_root(engine.game_state, session_dir / "checkpoints")

    intro_text = config.starting_state
    try:
        intro = engine.generate_intro()
        intro_text = str(intro.get("ic") or config.starting_state).strip()
    except Exception:
        st.warning("Intro generation failed. Using the configured starting state instead.")

    st.session_state.orchestrator = engine
    st.session_state.messages = [{"role": "assistant", "content": intro_text}]
    st.session_state.last_turn = {}
    st.session_state.turn_records = []
    st.session_state.config_signature = config.reset_signature()
    st.session_state.active_model = config.model
    st.session_state._engine_provider = config.provider
    st.session_state._engine_api_key = config.api_key
    st.session_state.active_story_key = config.story_key
    st.session_state.session_dir = str(session_dir)
    st.session_state.snapshot_files = []

    try:
        snapshot_path = write_session_checkpoint(session_dir, engine, 0)
        st.session_state.snapshot_files = [str(snapshot_path)]
    except Exception as exc:
        st.warning(f"Initial snapshot write failed: {exc}")

    clear_manual_roll_state(clear_pending_input=True)


def ensure_session(config: SessionConfig, *, reset_requested: bool) -> None:
    current_signature = config.reset_signature()
    if "orchestrator" not in st.session_state:
        initialize_session(config)
        return
    if reset_requested:
        initialize_session(config)


def sync_engine_provider_and_model(
    engine: StoryEngine,
    *,
    provider: str,
    api_key: str,
    model: str,
) -> None:
    """
    Hot-swap the live engine's provider, API key, and/or model when the
    sidebar selection diverges from what the engine was initialized with.
    Preserves chat history so the user doesn't lose state on every switch.
    """
    provider = str(provider or "").strip().lower()
    model = str(model or "").strip()
    api_key = str(api_key or "")

    last_provider = str(st.session_state.get("_engine_provider", "")).strip().lower()
    last_api_key = str(st.session_state.get("_engine_api_key", ""))
    last_model = str(st.session_state.get("active_model", "")).strip()

    provider_changed = bool(last_provider) and last_provider != provider
    api_key_changed = (
        provider in {"openai", "anthropic"}
        and last_api_key != api_key
    )

    if provider_changed or api_key_changed:
        try:
            from orchestrator.app_config import (
                get_provider_config,
                get_provider_default_options,
                get_provider_stage_options,
            )
            from orchestrator.llm_interaction.providers.factory import create_provider

            provider_config = dict(get_provider_config(provider))
            if api_key:
                provider_config["api_key"] = api_key
            new_provider = create_provider(provider, provider_config)
            engine.adapter.set_provider(
                new_provider,
                default_options=get_provider_default_options(provider),
                stage_options=get_provider_stage_options(provider),
            )
            st.session_state._engine_provider = provider
            st.session_state._engine_api_key = api_key
            if provider_changed:
                set_notice(f"Provider switched to '{provider}'. The next request will use it.")
            elif api_key_changed:
                set_notice(f"{provider.capitalize()} API key updated.")
        except Exception as exc:
            st.error(f"Failed to switch provider to '{provider}': {exc}")
            return

    if model and model != last_model:
        engine.adapter.model = model
        st.session_state.active_model = model
        if not provider_changed and not api_key_changed:
            set_notice(f"Model changed to '{model}'. The next request will use it.")


# Legacy alias — kept so any external callers continue to work.
def sync_engine_model(engine: StoryEngine, model: str) -> None:
    sync_engine_provider_and_model(
        engine,
        provider=str(st.session_state.get("_engine_provider", "")),
        api_key=str(st.session_state.get("_engine_api_key", "")),
        model=model,
    )


def get_story_engine() -> StoryEngine:
    return st.session_state.orchestrator


def build_sidebar(story_sources: list[StorySource]) -> tuple[SessionConfig, DisplayOptions, bool]:
    with st.sidebar:
        st.title("Session")

        if not story_sources:
            st.error("No stories are available. Add story folders under `orchestrator/world_state/data/stories`.")
            st.stop()

        source_by_key = {source.key: source for source in story_sources}
        selected_story_key = str(st.session_state.get("story_source_input", story_sources[0].key) or "")
        story_keys = [source.key for source in story_sources]
        if selected_story_key not in story_keys:
            selected_story_key = story_sources[0].key
        selected_story_key = st.selectbox(
            "Story",
            options=story_keys,
            index=story_keys.index(selected_story_key),
            key="story_source_input",
            format_func=lambda key: source_by_key[key].label,
        )
        story_source = source_by_key[selected_story_key]
        world_defaults = load_world_defaults(str(story_source.data_dir))
        if story_source.description:
            st.caption(story_source.description)
        st.caption(f"Story files: `{story_source.data_dir}`")

        provider_choices = get_provider_names()
        default_provider = get_default_provider()
        selected_provider = st.session_state.get("provider_input", default_provider)
        if selected_provider not in provider_choices:
            selected_provider = default_provider
        provider = st.selectbox(
            "Provider",
            options=provider_choices,
            index=provider_choices.index(selected_provider),
            key="provider_input",
        ) or default_provider

        # When the provider has changed since the engine was last initialized,
        # any previously-selected model belongs to the old provider (e.g.
        # "llama3.1:8b" left over from Ollama after switching to Anthropic).
        # Drop the stale key so the model selectbox renders with the new
        # provider's default rather than carrying invalid state forward.
        last_engine_provider = str(st.session_state.get("_engine_provider", "")).strip().lower()
        if last_engine_provider and last_engine_provider != provider:
            st.session_state.pop("model_input", None)

        _env_key_names = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
        api_key = ""
        if provider in _env_key_names:
            env_var = _env_key_names[provider]
            env_key = os.environ.get(env_var, "")
            key_input = st.text_input(
                f"{provider.capitalize()} API Key",
                value=st.session_state.get(f"{provider}_api_key_input", env_key),
                type="password",
                key=f"{provider}_api_key_input",
                placeholder=f"Loaded from {env_var}" if env_key else f"Paste your {env_var} here",
            )
            api_key = key_input.strip()
            if not api_key and not env_key:
                st.warning(f"No API key found. Set {env_var} or enter a key above.")

        model_choices = get_model_choices(provider)
        default_m = get_default_model(provider) if provider != "ollama" else get_ollama_default_model()
        selected_model = st.session_state.get("model_input", default_m)
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
                value=world_defaults.starting_location,
                key=f"starting_location_input_{story_source.key}",
            )
            starting_state = st.text_area(
                "Starting state",
                value=world_defaults.starting_state,
                height=180,
                key=f"starting_state_input_{story_source.key}",
            )

        reset_requested = st.button("Reset Session With Current Setup", use_container_width=True)
        st.caption("Model changes apply on the next request. Story selection and setup changes apply only after reset.")
        session_dir = str(st.session_state.get("session_dir") or "").strip()
        if session_dir:
            st.caption(f"Session files: `{session_dir}`")

        st.divider()
        show_debug_trace = st.checkbox("Show raw debug trace", value=False)

    config = SessionConfig(
        provider=str(provider or default_provider).strip().lower(),
        model=str(model or "").strip(),
        api_key=api_key,
        story_key=story_source.key,
        story_label=story_source.label,
        world_model_data_dir=str(story_source.data_dir),
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
    st.session_state.turn_records = [*st.session_state.get("turn_records", []), turn]
    session_dir = str(st.session_state.get("session_dir") or "").strip()
    if session_dir:
        try:
            snapshot_path = write_session_checkpoint(session_dir, engine, int(turn.get("turn", 0)))
            st.session_state.snapshot_files = [*st.session_state.get("snapshot_files", []), str(snapshot_path)]
        except Exception as exc:
            st.warning(f"Snapshot write failed: {exc}")
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


def parse_json_sequence(text: str, label: str) -> list[dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return []
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError(f"{label} must be a JSON array.")
    records: list[dict[str, Any]] = []
    for index, entry in enumerate(payload, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"{label} entry {index} must be a JSON object.")
        records.append(entry)
    return records


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


def world_model_records(engine: StoryEngine) -> dict[str, Any]:
    return {
        "story": engine.world.story_record(),
        "locations": engine.world.list_location_records(),
        "entities": engine.world.list_entity_records(),
        "items": engine.world.list_item_records(),
    }


def build_world_model_from_records(records: dict[str, Any]) -> WorldModel:
    story = dict(records.get("story") or {})
    model = WorldModel(
        starting_location=str(story.get("starting_location") or "").strip(),
        starting_state=str(story.get("starting_state") or "").strip(),
        beat_list=[str(beat).strip() for beat in story.get("beat_list") or [] if str(beat).strip()],
    )
    for payload in records.get("locations") or []:
        model.add_location(Location.from_record(dict(payload)))
    for payload in records.get("entities") or []:
        model.add_entity(Entity.from_record(dict(payload)))
    for payload in records.get("items") or []:
        model.add_item(Item.from_record(dict(payload)))
    model.sync_actor_inventories()
    return model


def apply_world_model_to_engine(
    engine: StoryEngine,
    model: WorldModel,
    *,
    sync_runtime_story_status: bool = False,
    move_player_to_start: bool = False,
) -> None:
    engine.world = model
    setattr(engine.game_state, "_runtime_world_model", model)
    old_index = int(getattr(engine.beats, "index", 0) or 0)
    max_index = max(0, len(model.beat_list) - 1)
    engine.beats = BeatTracker(list(model.beat_list), index=min(old_index, max_index))
    engine.beat_list = list(engine.beats.beats)
    if sync_runtime_story_status:
        engine.story_status = model.starting_state

    current_location = str(engine.game_state.player_location or "").strip()
    target_location = current_location
    if move_player_to_start and model.starting_location:
        target_location = model.starting_location
    elif current_location and model.get_location(current_location) is None:
        target_location = model.starting_location
    elif not current_location:
        target_location = model.starting_location

    if target_location and model.get_location(target_location) is not None:
        sync_player_location(engine, target_location)

    engine.game_state.discovered_keys.intersection_update(set(model.all_keys()))
    if engine.game_state.player_location:
        engine.game_state.discovered_keys.add(engine.game_state.player_location)
    sync_npc_locations(engine)
    engine.world.sync_actor_inventories()


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


def summarize_turn_label(turn: dict[str, Any]) -> str:
    turn_number = int(turn.get("turn", 0) or 0)
    summary = " ".join(str(turn.get("turn_summary") or "").split()).strip()
    if not summary:
        summary = " ".join(str(turn.get("narration", {}).get("ic") or "").split()).strip()
    if len(summary) > 72:
        summary = summary[:72].rstrip() + "..."
    return f"Turn {turn_number}: {summary or 'No summary'}"


def render_trace_messages(messages: list[dict[str, Any]]) -> None:
    if not messages:
        st.info("No loop message history was captured for this turn.")
        return

    for index, message in enumerate(messages, start=1):
        role = str(message.get("role") or "unknown").title()
        with st.expander(f"{index}. {role}", expanded=False):
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                st.markdown("**Tool Calls**")
                st.json(tool_calls, expanded=False)
            if message.get("tool_name"):
                st.markdown(f"**Tool Name:** `{message.get('tool_name')}`")
            if message.get("tool_call_id"):
                st.markdown(f"**Tool Call ID:** `{message.get('tool_call_id')}`")
            content = str(message.get("content") or "").strip()
            if content:
                st.code(content, language="markdown")
            else:
                st.write("No text content.")


def render_agent_rounds(rounds: list[dict[str, Any]]) -> None:
    if not rounds:
        st.info("No loop rounds were recorded for this turn.")
        return

    for round_info in rounds:
        iteration = int(round_info.get("iteration", 0) or 0)
        with st.expander(f"Iteration {iteration}", expanded=False):
            assistant_text = str(round_info.get("assistant_text") or "").strip()
            assistant_thinking = str(round_info.get("assistant_thinking") or "").strip()
            if assistant_text:
                st.markdown("**Assistant Response**")
                st.code(assistant_text, language="markdown")
            if assistant_thinking:
                st.markdown("**Assistant Thinking**")
                st.code(assistant_thinking, language="markdown")
            if round_info.get("tool_calls"):
                st.markdown("**Requested Tool Calls**")
                st.json(round_info.get("tool_calls"), expanded=False)
            if round_info.get("tool_results"):
                st.markdown("**Tool Results**")
                st.json(round_info.get("tool_results"), expanded=False)
            if round_info.get("hook_notes"):
                st.markdown("**Hook Notes**")
                st.json(round_info.get("hook_notes"), expanded=False)
            if round_info.get("response_block_reason"):
                st.warning(str(round_info.get("response_block_reason")))
            if round_info.get("stop_block_reason"):
                st.warning(str(round_info.get("stop_block_reason")))


def flatten_memory_delta(reconciliation: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    delta = dict(reconciliation.get("delta") or {})
    for change in delta.get("memory_changes") or []:
        entity = str(change.get("entity") or "")
        for line in change.get("added") or []:
            rows.append({"entity": entity, "change": "added", "memory": str(line)})
        for line in change.get("removed") or []:
            rows.append({"entity": entity, "change": "removed", "memory": str(line)})
    return rows


def render_world_delta(reconciliation: dict[str, Any]) -> None:
    if not reconciliation:
        st.info("No reconciliation report is available for this turn.")
        return

    delta = dict(reconciliation.get("delta") or {})
    player_location = dict(delta.get("player_location") or {})
    story_status = dict(delta.get("story_status") or {})

    metric_col_1, metric_col_2, metric_col_3 = st.columns(3)
    with metric_col_1:
        st.metric("Player Location", player_location.get("after") or "Unknown")
    with metric_col_2:
        st.metric("Entities Moved", len(delta.get("entity_location_changes") or []))
    with metric_col_3:
        st.metric("Memory Updates", len(delta.get("memory_changes") or []))

    if reconciliation.get("applied_fixes"):
        st.markdown("**Applied Fixes**")
        st.json(reconciliation.get("applied_fixes"), expanded=False)
    if reconciliation.get("validation_errors"):
        st.markdown("**Validation Errors**")
        st.json(reconciliation.get("validation_errors"), expanded=False)

    with st.expander("Location / Holder Changes", expanded=False):
        st.json(
            {
                "player_location": player_location,
                "npc_location_changes": delta.get("npc_location_changes") or [],
                "entity_location_changes": delta.get("entity_location_changes") or [],
                "item_holder_changes": delta.get("item_holder_changes") or [],
            },
            expanded=False,
        )
    with st.expander("Flags / Discovery", expanded=False):
        st.json(
            {
                "story_status": story_status,
                "discovered_keys": delta.get("discovered_keys") or {},
                "quest_flag_changes": delta.get("quest_flag_changes") or [],
            },
            expanded=False,
        )
    with st.expander("World Snapshots", expanded=False):
        st.json(
            {
                "before": reconciliation.get("world_before") or {},
                "after": reconciliation.get("world_after") or {},
            },
            expanded=False,
        )


def render_turn_inspector(display: DisplayOptions) -> None:
    turn_records = list(st.session_state.get("turn_records") or [])
    if not turn_records:
        return

    default_index = max(0, len(turn_records) - 1)
    selected_turn = st.selectbox(
        "Inspect Turn",
        options=list(range(len(turn_records))),
        index=default_index,
        format_func=lambda index: summarize_turn_label(turn_records[index]),
        key="turn_inspector_select",
    )
    turn = turn_records[int(selected_turn)]
    llm_trace = dict(turn.get("llm_trace") or {})
    agent_trace = dict(llm_trace.get("AGENT") or {})
    narrate_trace = dict(llm_trace.get("NARRATE") or {})
    reconciliation = dict(turn.get("reconciliation") or {})

    summary_tab, messages_tab, rounds_tab, world_tab, memory_tab, raw_tab = st.tabs(
        ["Summary", "LLM Messages", "LLM Rounds", "World Delta", "Memory", "Raw"]
    )

    with summary_tab:
        st.markdown(f"**Turn Summary:** {turn.get('turn_summary') or 'None'}")
        if str(turn.get("blocked_reason") or "").strip():
            st.markdown(f"**Blocked Reason:** {turn.get('blocked_reason')}")
        if str(turn.get("narration_focus") or "").strip():
            st.markdown(f"**Narration Focus:** {turn.get('narration_focus')}")
        st.markdown("**Narration**")
        st.write(str(turn.get("narration", {}).get("ic") or "").strip() or "No narration recorded.")
        if turn.get("phase_summaries"):
            with st.expander("Phase Summaries", expanded=False):
                st.json(turn.get("phase_summaries"), expanded=False)
        if turn.get("tool_calls"):
            with st.expander("Action Tool Calls", expanded=False):
                st.json(turn.get("tool_calls"), expanded=False)
        if turn.get("world_tool_calls"):
            with st.expander("All World Tool Calls", expanded=False):
                st.json(turn.get("world_tool_calls"), expanded=False)
        if turn.get("turn_todo"):
            with st.expander("Turn Todo", expanded=False):
                st.json(turn.get("turn_todo"), expanded=False)
        if agent_trace.get("prompt"):
            with st.expander("Agent Prompt", expanded=False):
                st.code(str(agent_trace.get("prompt") or ""), language="markdown")
        if narrate_trace.get("prompt"):
            with st.expander("Narration Prompt", expanded=False):
                st.code(str(narrate_trace.get("prompt") or ""), language="markdown")

    with messages_tab:
        agent_messages, narrate_attempts = st.tabs(["Agent Loop", "Narration Step"])
        with agent_messages:
            render_trace_messages(list(agent_trace.get("messages") or []))
        with narrate_attempts:
            attempts = list(narrate_trace.get("attempts") or [])
            if not attempts:
                st.info("No narration attempts were captured.")
            for attempt in attempts:
                attempt_number = int(attempt.get("attempt", 0) or 0)
                with st.expander(f"Attempt {attempt_number}", expanded=False):
                    if attempt.get("prompt"):
                        st.markdown("**Prompt**")
                        st.code(str(attempt.get("prompt") or ""), language="markdown")
                    if attempt.get("raw"):
                        st.markdown("**Raw Output**")
                        st.code(str(attempt.get("raw") or ""), language="markdown")
                    if attempt.get("sections"):
                        st.markdown("**Parsed Sections**")
                        st.json(attempt.get("sections"), expanded=False)
                    if attempt.get("error"):
                        st.error(str(attempt.get("error")))

    with rounds_tab:
        render_agent_rounds(list(agent_trace.get("rounds") or []))

    with world_tab:
        render_world_delta(reconciliation)

    with memory_tab:
        memory_rows = flatten_memory_delta(reconciliation)
        if memory_rows:
            st.dataframe(memory_rows, use_container_width=True)
        else:
            st.info("No memory delta was detected for this turn.")
        if reconciliation.get("turn_memory"):
            st.markdown("**Turn Memory Entry**")
            st.code(str(reconciliation.get("turn_memory") or ""), language="markdown")
        conversation_entry = reconciliation.get("conversation_entry") or {}
        if conversation_entry:
            with st.expander("Conversation Entry", expanded=False):
                st.json(conversation_entry, expanded=False)

    with raw_tab:
        if llm_trace:
            st.json(llm_trace, expanded=False)
        else:
            st.write("No debug trace is available yet.")
        if display.show_debug_trace:
            st.markdown("**Full Turn Payload**")
            st.json(turn, expanded=False)


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


def render_story_authoring(engine: StoryEngine) -> None:
    st.subheader("Story")
    st.caption("Edit the authored story record that seeds a session: starting location, premise, and beat guide.")

    location_keys = sorted_location_keys(engine)
    current_start = engine.world.starting_location
    if current_start not in location_keys and current_start:
        location_keys = [current_start, *location_keys]

    form_col, preview_col = st.columns([1.4, 1], gap="large")
    with form_col:
        with st.form("story_authoring_form"):
            if location_keys:
                starting_location = st.selectbox(
                    "Starting location",
                    options=location_keys,
                    index=location_keys.index(current_start) if current_start in location_keys else 0,
                    key="story_authoring_starting_location",
                )
            else:
                starting_location = st.text_input(
                    "Starting location",
                    value=current_start,
                    key="story_authoring_starting_location_text",
                )
            starting_state = st.text_area(
                "Starting state",
                value=engine.world.starting_state,
                height=220,
            )
            beat_list_text = st.text_area(
                "Beat list",
                value=format_lines(engine.world.beat_list),
                height=240,
                help="One beat per line.",
            )
            current_index = engine.beats.index if engine.beats.beats else 0
            sync_status = st.checkbox(
                "Also replace current runtime story status",
                value=False,
                key="story_authoring_sync_status",
                help="Use this when the new premise should replace the live session status immediately.",
            )
            move_player_to_start = st.checkbox(
                "Move player to starting location",
                value=False,
                key="story_authoring_move_player_to_start",
                help="Use this when the authored starting location should become the current live location.",
            )
            submitted = st.form_submit_button("Apply Story Changes", use_container_width=True)

        if submitted:
            beats = parse_text_lines(beat_list_text)
            engine.world.set_story(
                starting_location=starting_location,
                starting_state=starting_state,
                beat_list=beats,
            )
            errors = engine.world.validate()
            if errors:
                st.error("\n".join(errors))
                return
            engine.beats = BeatTracker(beats, index=min(current_index, max(0, len(beats) - 1)))
            engine.beat_list = list(engine.beats.beats)
            if sync_status:
                engine.story_status = engine.world.starting_state
            if move_player_to_start:
                sync_player_location(engine, engine.world.starting_location)
            set_notice("Story record updated.")
            st.rerun()

    with preview_col:
        st.markdown("**Current Record**")
        st.json(engine.world.story_record(), expanded=False)
        st.markdown("**Runtime Beat State**")
        st.json(
            {
                "current_index": engine.beats.index,
                "current": engine.beats.current(),
                "next": engine.beats.next(),
                "total": len(engine.beats.beats),
            },
            expanded=False,
        )


def render_data_characteristics(engine: StoryEngine) -> None:
    st.subheader("Data Map")
    st.caption("Authored content is stored in the world model; runtime fields are mutable session state.")

    story_record = engine.world.story_record()
    rows = [
        {
            "domain": "story",
            "records": 1,
            "fields": "starting_location, starting_state, beat_list",
            "authorable_now": "yes",
            "should_add": "title, synopsis, genre/tone, act/quest ids, success/failure resolution notes",
        },
        {
            "domain": "locations",
            "records": len(engine.world.locations),
            "fields": "key, name, description, connections, tags",
            "authorable_now": "yes",
            "should_add": "read-aloud text, secrets, DCs, ambient details, locked/hidden exits",
        },
        {
            "domain": "entities",
            "records": len(engine.world.entities),
            "fields": "key, name, entity_type, description, location, skills, stats, tags, memory",
            "authorable_now": "yes",
            "should_add": "goals, secrets, attitude, dialogue hooks, schedule, faction, relationship edges",
        },
        {
            "domain": "items",
            "records": len(engine.world.items),
            "fields": "key, name, description, holder_kind, holder_key, portable, tags",
            "authorable_now": "yes",
            "should_add": "mechanical effects, clue payloads, rarity/value, discovery requirements",
        },
        {
            "domain": "runtime",
            "records": len(engine.game_state.discovered_keys),
            "fields": "player_location, discovered_keys, quest_flags, story_status, summary, current beat",
            "authorable_now": "yes, live session only",
            "should_add": "named milestones, journal entries, authored flag definitions",
        },
        {
            "domain": "memory",
            "records": sum(entity.memory_count for entity in engine.world.entities.values()),
            "fields": "per-entity sentence memory",
            "authorable_now": "yes",
            "should_add": "source/type, confidence, visibility, chronology, expiration/pinning",
        },
    ]
    st.dataframe(rows, use_container_width=True)

    st.markdown("**Current Story Shape**")
    st.json(
        {
            "starting_location_exists": bool(engine.world.get_location(story_record.get("starting_location", ""))),
            "beat_count": len(story_record.get("beat_list") or []),
            "location_count": len(engine.world.locations),
            "entity_count": len(engine.world.entities),
            "item_count": len(engine.world.items),
            "validation_errors": engine.world.validate(),
        },
        expanded=False,
    )


def render_bulk_world_model_editor(engine: StoryEngine) -> None:
    st.subheader("Bulk Rewrite")
    st.caption("Replace the complete authored world model in memory. The replacement is validated before it is applied.")

    current_records = world_model_records(engine)
    with st.form("bulk_world_model_editor_form"):
        story_text = st.text_area("story.json", value=format_json(current_records["story"]), height=220)
        locations_text = st.text_area("locations.json", value=format_json(current_records["locations"]), height=260)
        entities_text = st.text_area("actors.json", value=format_json(current_records["entities"]), height=260)
        items_text = st.text_area("items.json", value=format_json(current_records["items"]), height=260)
        sync_status = st.checkbox(
            "Also replace current runtime story status",
            value=False,
            key="bulk_world_model_sync_status",
        )
        move_player_to_start = st.checkbox(
            "Move player to starting location",
            value=False,
            key="bulk_world_model_move_player_to_start",
        )
        submitted = st.form_submit_button("Validate And Replace World Model", use_container_width=True)

    if submitted:
        try:
            replacement_records = {
                "story": parse_json_mapping(story_text),
                "locations": parse_json_sequence(locations_text, "locations.json"),
                "entities": parse_json_sequence(entities_text, "actors.json"),
                "items": parse_json_sequence(items_text, "items.json"),
            }
            replacement = build_world_model_from_records(replacement_records)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            st.error(f"Invalid world model JSON: {exc}")
            return

        errors = replacement.validate()
        if errors:
            st.error("\n".join(errors))
            return

        apply_world_model_to_engine(
            engine,
            replacement,
            sync_runtime_story_status=sync_status,
            move_player_to_start=move_player_to_start,
        )
        set_notice("World model replaced.")
        st.rerun()

    source_dir = Path(str(getattr(engine.game_state, "_world_model_data_dir", "") or "")).expanduser()
    st.divider()
    save_col, checkpoint_col = st.columns(2)
    with save_col:
        if st.button("Save Current World Model To Source Files", use_container_width=True):
            try:
                engine.world.save(source_dir)
            except Exception as exc:
                st.error(f"Save failed: {exc}")
            else:
                set_notice(f"World model saved to {source_dir}.")
                st.rerun()
    with checkpoint_col:
        if st.button("Write Session Checkpoint", use_container_width=True):
            session_dir = str(st.session_state.get("session_dir") or "").strip()
            if not session_dir:
                st.error("No session directory is active.")
            else:
                try:
                    snapshot_path = write_session_checkpoint(session_dir, engine, int(engine.turn_index))
                    st.session_state.snapshot_files = [*st.session_state.get("snapshot_files", []), str(snapshot_path)]
                except Exception as exc:
                    st.error(f"Checkpoint write failed: {exc}")
                else:
                    set_notice(f"Checkpoint written to {snapshot_path}.")
                    st.rerun()


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
    session_dir = str(st.session_state.get("session_dir") or "").strip()
    snapshot_files = list(st.session_state.get("snapshot_files") or [])

    if validation_errors:
        st.warning("\n".join(validation_errors))
    else:
        st.success("World model validation passed.")

    if session_dir:
        st.caption(f"Session snapshot directory: `{session_dir}`")
    if snapshot_files:
        st.caption(f"Saved snapshots: {len(snapshot_files)}")

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
    story_tab, runtime_tab, location_tab, entity_tab, item_tab, memory_tab, data_tab, bulk_tab, snapshot_tab = st.tabs(
        ["Story", "Runtime", "Locations", "Entities", "Items", "Memory", "Data Map", "Bulk JSON", "Browse"]
    )

    with story_tab:
        render_story_authoring(engine)
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
    with data_tab:
        render_data_characteristics(engine)
    with bulk_tab:
        render_bulk_world_model_editor(engine)
    with snapshot_tab:
        render_snapshot_browser(engine, display)


def main() -> None:
    st.set_page_config(page_title="Dungeon Master's Companion", layout="wide")
    ensure_runtime_state()

    story_sources = list_story_sources()
    session_config, display, reset_requested = build_sidebar(story_sources)
    ensure_session(session_config, reset_requested=reset_requested)

    engine = get_story_engine()
    sync_engine_provider_and_model(
        engine,
        provider=session_config.provider,
        api_key=session_config.api_key,
        model=session_config.model,
    )
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
            render_turn_inspector(display)
            render_world_graph(snapshot)
            render_debug_trace(display)

    with editor_tab:
        render_world_state_editor(engine, display)


if __name__ == "__main__":
    main()

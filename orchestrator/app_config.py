from __future__ import annotations

import copy
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

CONFIG_PATH_ENV_VAR = "DMC_CONFIG_PATH"
_DEFAULT_CONFIG_PATH = Path(__file__).with_name("app_config.json")

SUPPORTED_PROVIDERS = ("ollama", "openai", "anthropic")


@lru_cache(maxsize=1)
def _load_config() -> dict[str, Any]:
    config_path = Path(os.environ.get(CONFIG_PATH_ENV_VAR, _DEFAULT_CONFIG_PATH))
    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be an object: {config_path}")
    return data


# ---------------------------------------------------------------------------
# Provider-agnostic helpers (preferred API)
# ---------------------------------------------------------------------------

def get_active_provider() -> str:
    """Return the name of the active LLM provider ('ollama', 'openai', 'anthropic')."""
    name = str(_load_config().get("provider", "ollama")).strip().lower()
    if name not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Config key 'provider' must be one of {SUPPORTED_PROVIDERS}, got '{name}'"
        )
    return name


def get_provider_config(provider: str | None = None) -> dict[str, Any]:
    """Return the config section for the given (or active) provider."""
    name = str(provider or get_active_provider()).strip().lower()
    section = _load_config().get(name, {})
    if not isinstance(section, dict):
        raise ValueError(f"Config key '{name}' must be an object")
    return copy.deepcopy(section)


def get_active_model() -> str:
    """Return the default model for the active provider."""
    provider = get_active_provider()
    section = get_provider_config(provider)
    model = section.get("default_model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError(
            f"Config key '{provider}.default_model' must be a non-empty string"
        )
    return model.strip()


def get_active_model_choices() -> list[str]:
    """Return the model choices list for the active provider."""
    provider = get_active_provider()
    section = get_provider_config(provider)
    default_model = get_active_model()
    raw = section.get("model_choices")
    if raw is None:
        return [default_model]
    if not isinstance(raw, list):
        raise ValueError(f"Config key '{provider}.model_choices' must be an array")
    choices = [str(m).strip() for m in raw if str(m).strip()]
    if not choices:
        return [default_model]
    if default_model not in choices:
        choices.insert(0, default_model)
    return choices


def get_active_default_options() -> dict[str, Any]:
    """Return the default inference options for the active provider."""
    provider = get_active_provider()
    section = get_provider_config(provider)
    opts = section.get("default_options", {})
    if not isinstance(opts, dict):
        raise ValueError(f"Config key '{provider}.default_options' must be an object")
    return copy.deepcopy(opts)


def get_active_stage_options() -> dict[str, dict[str, Any]]:
    """Return per-stage inference option overrides for the active provider."""
    provider = get_active_provider()
    section = get_provider_config(provider)
    stage_opts = section.get("stage_options", {})
    if not isinstance(stage_opts, dict):
        raise ValueError(f"Config key '{provider}.stage_options' must be an object")
    return copy.deepcopy(stage_opts)


# ---------------------------------------------------------------------------
# Backward-compatible Ollama-specific helpers (used by pipeline.py / benchmark)
# ---------------------------------------------------------------------------

def _get_ollama_section() -> dict[str, Any]:
    section = _load_config().get("ollama", {})
    if not isinstance(section, dict):
        raise ValueError("Config key 'ollama' must be an object")
    return section


def get_ollama_default_model() -> str:
    model = _get_ollama_section().get("default_model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Config key 'ollama.default_model' must be a non-empty string")
    return model.strip()


def get_ollama_model_choices() -> list[str]:
    default_model = get_ollama_default_model()
    raw = _get_ollama_section().get("model_choices")
    if raw is None:
        return [default_model]
    if not isinstance(raw, list):
        raise ValueError("Config key 'ollama.model_choices' must be an array of strings")
    choices = [str(m).strip() for m in raw if str(m).strip()]
    if not choices:
        raise ValueError("Config key 'ollama.model_choices' must contain at least one entry")
    if default_model not in choices:
        choices.insert(0, default_model)
    return choices


def get_ollama_default_options() -> dict[str, Any]:
    opts = _get_ollama_section().get("default_options", {})
    if not isinstance(opts, dict):
        raise ValueError("Config key 'ollama.default_options' must be an object")
    return copy.deepcopy(opts)


def get_ollama_stage_options() -> dict[str, dict[str, Any]]:
    stage_opts = _get_ollama_section().get("stage_options", {})
    if not isinstance(stage_opts, dict):
        raise ValueError("Config key 'ollama.stage_options' must be an object")
    return copy.deepcopy(stage_opts)


# ---------------------------------------------------------------------------
# Roll mode
# ---------------------------------------------------------------------------

def get_roll_mode() -> str:
    rolls = _load_config().get("rolls", {})
    if not isinstance(rolls, dict):
        raise ValueError("Config key 'rolls' must be an object")
    mode = str(rolls.get("mode", "auto")).strip().lower()
    if mode not in {"auto", "manual"}:
        raise ValueError("Config key 'rolls.mode' must be 'auto' or 'manual'")
    return mode

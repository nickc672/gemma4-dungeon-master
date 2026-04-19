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
# Internal: resolve the llm section, with backwards compat for old configs
# that only had a top-level "ollama" key.
# ---------------------------------------------------------------------------

def _get_llm_section() -> dict[str, Any]:
    config = _load_config()
    llm = config.get("llm")
    if llm is not None:
        if not isinstance(llm, dict):
            raise ValueError("Config key 'llm' must be an object")
        return llm
    # Legacy flat config: {"ollama": {...}, "rolls": {...}}
    return {
        "default_provider": "ollama",
        "providers": {"ollama": _get_ollama_section_raw()},
    }


def _get_provider_section(provider: str) -> dict[str, Any]:
    name = str(provider or "").strip().lower() or get_default_provider()
    providers = _get_llm_section().get("providers", {})
    if not isinstance(providers, dict):
        raise ValueError("Config key 'llm.providers' must be an object")
    section = providers.get(name)
    if section is None:
        raise ValueError(
            f"Unknown provider '{name}'. "
            f"Available: {', '.join(get_provider_names())}"
        )
    if not isinstance(section, dict):
        raise ValueError(f"Config key 'llm.providers.{name}' must be an object")
    return section


# ---------------------------------------------------------------------------
# Provider-agnostic helpers (primary API)
# ---------------------------------------------------------------------------

def get_default_provider() -> str:
    """Return the name of the configured default LLM provider."""
    name = str(_get_llm_section().get("default_provider", "ollama")).strip().lower()
    if not name:
        raise ValueError("Config key 'llm.default_provider' must be a non-empty string")
    return name


def get_provider_names() -> list[str]:
    """Return all configured provider names, default first."""
    providers = _get_llm_section().get("providers", {})
    if not isinstance(providers, dict):
        return [get_default_provider()]
    names = [str(k).strip().lower() for k in providers if str(k).strip()]
    default = get_default_provider()
    if default not in names:
        names.insert(0, default)
    return list(dict.fromkeys(names))  # dedupe, preserve order


def get_provider_config(provider: str | None = None) -> dict[str, Any]:
    """Return a copy of the config section for the given (or default) provider."""
    return copy.deepcopy(_get_provider_section(provider or get_default_provider()))


def get_default_model(provider: str | None = None) -> str:
    """Return the default model for the given (or default) provider."""
    name = str(provider or get_default_provider()).strip().lower()
    section = _get_provider_section(name)
    model = section.get("default_model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError(
            f"Config key 'llm.providers.{name}.default_model' must be a non-empty string"
        )
    return model.strip()


def get_model_choices(provider: str | None = None) -> list[str]:
    """Return the model choices list for the given (or default) provider."""
    name = str(provider or get_default_provider()).strip().lower()
    default_model = get_default_model(name)
    raw = _get_provider_section(name).get("model_choices")
    if raw is None:
        return [default_model]
    if not isinstance(raw, list):
        raise ValueError(
            f"Config key 'llm.providers.{name}.model_choices' must be an array"
        )
    choices = [str(m).strip() for m in raw if str(m).strip()]
    if default_model not in choices:
        choices.insert(0, default_model)
    return choices


def get_provider_default_options(provider: str | None = None) -> dict[str, Any]:
    """Return the default inference options for the given (or default) provider."""
    name = str(provider or get_default_provider()).strip().lower()
    opts = _get_provider_section(name).get("default_options", {})
    if not isinstance(opts, dict):
        raise ValueError(
            f"Config key 'llm.providers.{name}.default_options' must be an object"
        )
    return copy.deepcopy(opts)


def get_provider_stage_options(provider: str | None = None) -> dict[str, dict[str, Any]]:
    """Return per-stage option overrides for the given (or default) provider."""
    name = str(provider or get_default_provider()).strip().lower()
    stage_opts = _get_provider_section(name).get("stage_options", {})
    if not isinstance(stage_opts, dict):
        raise ValueError(
            f"Config key 'llm.providers.{name}.stage_options' must be an object"
        )
    return copy.deepcopy(stage_opts)


# Aliases kept so existing imports continue to work
get_active_provider = get_default_provider
get_active_model = get_default_model
get_active_model_choices = get_model_choices
get_active_default_options = get_provider_default_options
get_active_stage_options = get_provider_stage_options


# ---------------------------------------------------------------------------
# Backwards-compatible Ollama-specific helpers
# ---------------------------------------------------------------------------

def _get_ollama_section_raw() -> dict[str, Any]:
    section = _load_config().get("ollama", {})
    if not isinstance(section, dict):
        raise ValueError("Config key 'ollama' must be an object")
    return section


def _get_ollama_section() -> dict[str, Any]:
    # Prefer llm.providers.ollama when present; fall back to legacy top-level key.
    try:
        return _get_provider_section("ollama")
    except ValueError:
        return _get_ollama_section_raw()


def get_ollama_default_model() -> str:
    model = _get_ollama_section().get("default_model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Config key 'ollama.default_model' must be a non-empty string")
    return model.strip()


def get_ollama_model_choices() -> list[str]:
    return get_model_choices("ollama")


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

from __future__ import annotations

import copy
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

CONFIG_PATH_ENV_VAR = "DMC_CONFIG_PATH"
_DEFAULT_CONFIG_PATH = Path(__file__).with_name("app_config.json")


@lru_cache(maxsize=1)
def _load_config() -> dict[str, Any]:
    config_path = Path(os.environ.get(CONFIG_PATH_ENV_VAR, _DEFAULT_CONFIG_PATH))
    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be an object: {config_path}")
    return data


def _get_model_section() -> dict[str, Any]:
    section = _load_config().get("model", {})
    if not isinstance(section, dict):
        raise ValueError("Config key 'model' must be an object")
    return section


# ---------------------------------------------------------------------------
# Model helpers
# ---------------------------------------------------------------------------

def get_default_model() -> str:
    """Return the configured default model name."""
    section = _get_model_section()
    model = section.get("default")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Config key 'model.default' must be a non-empty string")
    return model.strip()


def get_model_choices() -> list[str]:
    """Return the configured list of model choices, default first."""
    default_model = get_default_model()
    raw = _get_model_section().get("choices")
    if raw is None:
        return [default_model]
    if not isinstance(raw, list):
        raise ValueError("Config key 'model.choices' must be an array")
    choices = [str(m).strip() for m in raw if str(m).strip()]
    if default_model not in choices:
        choices.insert(0, default_model)
    return choices


def get_default_options() -> dict[str, Any]:
    """Return the default inference options."""
    opts = _get_model_section().get("default_options", {})
    if not isinstance(opts, dict):
        raise ValueError("Config key 'model.default_options' must be an object")
    return copy.deepcopy(opts)


def get_stage_options() -> dict[str, dict[str, Any]]:
    """Return per-stage option overrides."""
    stage_opts = _get_model_section().get("stage_options", {})
    if not isinstance(stage_opts, dict):
        raise ValueError("Config key 'model.stage_options' must be an object")
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
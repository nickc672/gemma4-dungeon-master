from __future__ import annotations

import os
from typing import Any

from .base import LLMProvider


def create_provider(provider_name: str, config: dict[str, Any]) -> LLMProvider:
    """
    Instantiate an LLMProvider from the named provider and its config section.

    API keys are resolved in priority order:
      1. Explicit ``api_key`` field in the config section.
      2. Environment variable named by ``api_key_env`` (defaults to the
         standard OPENAI_API_KEY / ANTHROPIC_API_KEY names).
      3. The standard environment variable for that provider as a fallback.

    Args:
        provider_name: "ollama", "openai", or "anthropic"
        config: The provider's config dict (e.g. app_config["llm"]["providers"]["openai"])
    """
    name = str(provider_name).strip().lower()

    if name == "ollama":
        from .ollama import OllamaProvider
        return OllamaProvider()

    if name == "openai":
        from .openai import OpenAIProvider
        api_key = _resolve_api_key(config, env_var=config.get("api_key_env", "OPENAI_API_KEY"))
        return OpenAIProvider(api_key=api_key)

    if name == "anthropic":
        from .anthropic import AnthropicProvider
        api_key = _resolve_api_key(config, env_var=config.get("api_key_env", "ANTHROPIC_API_KEY"))
        return AnthropicProvider(api_key=api_key)

    raise ValueError(
        f"Unknown provider '{provider_name}'. "
        "Supported providers: 'ollama', 'openai', 'anthropic'."
    )


def _resolve_api_key(config: dict[str, Any], *, env_var: str) -> str | None:
    """Return explicit key from config, or read from the named env variable."""
    explicit = str(config.get("api_key", "")).strip()
    if explicit:
        return explicit
    return os.environ.get(str(env_var).strip()) or None


__all__ = ["create_provider"]

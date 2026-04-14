from __future__ import annotations

from typing import Any

from .base import LLMProvider


def create_provider(provider_name: str, config: dict[str, Any]) -> LLMProvider:
    """
    Instantiate an LLMProvider from the named provider and its config section.

    Args:
        provider_name: "ollama", "openai", or "anthropic"
        config: The provider's config dict (e.g. app_config["openai"])

    Returns:
        An LLMProvider instance ready for use.
    """
    name = str(provider_name).strip().lower()

    if name == "ollama":
        from .ollama import OllamaProvider
        return OllamaProvider()

    if name == "openai":
        from .openai import OpenAIProvider
        api_key = str(config.get("api_key", "")).strip() or None
        return OpenAIProvider(api_key=api_key)

    if name == "anthropic":
        from .anthropic import AnthropicProvider
        api_key = str(config.get("api_key", "")).strip() or None
        return AnthropicProvider(api_key=api_key)

    raise ValueError(
        f"Unknown provider '{provider_name}'. "
        "Supported providers: 'ollama', 'openai', 'anthropic'."
    )


__all__ = ["create_provider"]

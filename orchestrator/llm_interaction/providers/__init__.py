from .base import LLMProvider, LLMResponse, ToolCall
from .factory import create_provider

__all__ = ["LLMProvider", "LLMResponse", "ToolCall", "create_provider"]

"""
==================================================
ORCHESTRATOR / LLM_INTERACTION / PROVIDERS
==================================================

WHAT THIS IS

This folder is where the code that actually calls each AI service lives.
The rest of the system does not need to know whether it is talking to Ollama, OpenAI, or Anthropic.
It just uses whichever provider is configured, and one of the files in this folder handles the actual API call.

The providers each understand the same input (a prompt plus optional tool definitions) and they all return the same output (a normalized response).

The default provider (Ollama) is loaded whenever the game starts.
The other two (OpenAI, Anthropic) are only loaded if the configuration actually points to them.
This is so you don't need an API key for a service you are not using.


WHAT EACH PROVIDER MUST DO

The providers all follow the same contract.
For one request, a provider must:
- Send one chat completion request, with optional tool definitions.
- Return a normalized "LLMResponse" with the assistant's text, any tool calls the AI made, and any thinking blocks.
- Translate tool-call argument shapes so the rest of the codebase does not have to care about the differences between OpenAI, Anthropic, and Ollama formats.

Because they all follow the same contract, the agent loop ("agent_loop.py") can talk to any of them through the shared interface without caring which one it is.


====================
FILES IN THIS FOLDER
====================

- "base.py"
    The shared contract.
    Defines: 
      - the "LLMProvider" protocol (the methods every provider must implement)
      - the "LLMResponse" dataclass (the shape of a reply)
      - the "ToolCall" dataclass (the shape of a tool invocation by the AI).
    Everything in "agent_loop.py" is written against these shared types.

- "factory.py"
    The provider picker.
    Defines "create_provider(name, config)", which imports the requested provider module and returns an instance.
    Handles API key resolution:
      - first checks for an explicit "api_key" field in the config
      - then looks at whatever environment variable name is in "api_key_env"
      - finally, falls back to the standard names ("OPENAI_API_KEY", "ANTHROPIC_API_KEY").
    The importing is set up in a way that a missing dependency only causes an error if you actually try to use that provider.

- "__init__.py"
    Re-exports "LLMProvider", "LLMResponse", "ToolCall", and "create_provider".
    This is just to keep import statements short elsewhere in the codebase.

- "ollama.py"
    Defines "OllamaProvider".
    Talks to a locally running Ollama server using the official "ollama" Python client.
    Uses "get_shared_instance()" so the codebase reuses one HTTP client rather than spawning a new one per call.
    This is the default provider in "app_config.json", because it does not need an API key and runs entirely on the user's machine.

- "openai.py"
    Defines "OpenAIProvider".
    Talks to OpenAI's Chat Completions API.
    Requires the "OPENAI_API_KEY" environment variable to be set (or whatever name is configured in "api_key_env").

- "anthropic.py"
    Defines "AnthropicProvider".
    Talks to Anthropic's Messages API.
    Requires the "ANTHROPIC_API_KEY" environment variable.
    This file also handles translating Anthropic's "tool_use" content blocks into the shared "ToolCall" shape that the rest of the codebase expects.


=================================
HOW THE PROVIDER GETS CHOSEN
=================================

The provider is decided at startup, in this order:

1. An explicit "--provider" flag passed to "cli.py", or the equivalent constructor argument given to "StoryEngine".
2. The provider dropdown in the Streamlit sidebar.
3. The "llm.default_provider" value in "app_config.json".

Once chosen, the same provider is used for the session, but may be switched per response in the streamlit application.
"""
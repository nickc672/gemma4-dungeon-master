"""Interactive story orchestration utilities."""

from typing import Any

__all__ = ["Orchestrator"]


def __getattr__(name: str) -> Any:
    if name == "Orchestrator":
        from .pipeline import Orchestrator

        return Orchestrator
    raise AttributeError(name)

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class TurnContext:
    data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def fresh(
        cls,
        *,
        current_location: str,
        roll_mode: str,
        manual_roll_provider: Optional[Callable[[Dict[str, Any]], int]] = None,
    ) -> "TurnContext":
        """Build a new turn context with all required fields initialised."""
        return cls(data={
            "phase": "phase_one",
            "todo": [],
            "todo_revision": 0,
            "todo_summary": "",
            "notes": [],
            "all_world_tool_calls": [],
            "current_location": current_location,
            "finalize": None,
            "finalize_writes": None,
            "roll_mode": roll_mode,
            "manual_roll_provider": (
                manual_roll_provider if roll_mode == "manual" else None
            ),
            # Populated by check_can_interact when a player-named target cannot be resolved to an existing world object.
            "unresolved_interaction_targets": [],
            # Tracks how many entities/items have been created this turn.
            "creation_counts": {"entities": 0, "items": 0},
            # Phase 1 read-tool cache (deduplicates repeated reads after a validation rejection).
            "phase_one_tool_cache": {},
        })

    def as_dict(self) -> Dict[str, Any]:
        """Return the underlying mutable dict for binding to game_state."""
        return self.data


    # Phase tracking

    @property
    def phase(self) -> str:
        return str(self.data.get("phase") or "")

    @phase.setter
    def phase(self, value: str) -> None:
        self.data["phase"] = str(value or "")


    # Finalize payloads

    @property
    def finalize(self) -> Optional[Dict[str, Any]]:
        return self.data.get("finalize")

    @finalize.setter
    def finalize(self, value: Optional[Dict[str, Any]]) -> None:
        self.data["finalize"] = value

    @property
    def finalize_writes(self) -> Optional[Dict[str, Any]]:
        return self.data.get("finalize_writes")

    @finalize_writes.setter
    def finalize_writes(self, value: Optional[Dict[str, Any]]) -> None:
        self.data["finalize_writes"] = value


    # Tool call accumulators

    @property
    def all_world_tool_calls(self) -> List[Dict[str, Any]]:
        return self.data["all_world_tool_calls"]

    def append_tool_call(self, call: Dict[str, Any]) -> None:
        self.data["all_world_tool_calls"].append(call)

    def calls_for_phase(self, phase: str) -> List[Dict[str, Any]]:
        return [c for c in self.data["all_world_tool_calls"] if c.get("phase") == phase]


    # Location and resolution

    @property
    def current_location(self) -> str:
        return str(self.data.get("current_location") or "")

    @current_location.setter
    def current_location(self, value: str) -> None:
        self.data["current_location"] = str(value or "")

    @property
    def unresolved_interaction_targets(self) -> List[Any]:
        return self.data.get("unresolved_interaction_targets", [])


    # Roll mode and provider

    @property
    def roll_mode(self) -> str:
        return str(self.data.get("roll_mode") or "auto")

    @property
    def manual_roll_provider(self) -> Optional[Callable[[Dict[str, Any]], int]]:
        return self.data.get("manual_roll_provider")


    # Phase 1 read-tool cache

    @property
    def phase_one_tool_cache(self) -> Dict[str, Dict[str, Any]]:
        cache = self.data.setdefault("phase_one_tool_cache", {})
        return cache


    # Todo list (populated by world tools, not the pipeline)

    @property
    def todo(self) -> List[Any]:
        return self.data.get("todo", [])


__all__ = ["TurnContext"]
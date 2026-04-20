from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from ..world_state.tool_runtime import save_runtime_world_checkpoint


@dataclass
class BeatTracker:
    beats: List[str]
    index: int = 0

    def current(self) -> str:
        return self.beats[self.index] if self.beats else ""

    def next(self) -> str:
        if not self.beats:
            return ""
        nxt = self.index + 1
        return self.beats[nxt] if 0 <= nxt < len(self.beats) else ""

    def progress_text(self) -> str:
        if not self.beats:
            return "No beats provided."
        return f"{self.index + 1}/{len(self.beats)}: {self.current()}"

    def advance(self) -> None:
        if self.index + 1 < len(self.beats):
            self.index += 1


class SessionSummary:
    """Compact rolling summary of the session (player + recap highlights)."""

    def __init__(
        self,
        max_items: Optional[int] = None,
        max_chars: Optional[int] = None,
    ) -> None:
        self.events: List[str] = []
        self.max_items = max_items
        self.max_chars = max_chars

    def add(self, label: str, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        entry = f"{label}: {cleaned}"
        self.events.append(entry)
        self._trim()

    def text(self) -> str:
        return "\n".join(self.events)

    def _trim(self) -> None:
        if self.max_items is None and self.max_chars is None:
            return

        while True:
            if self.max_items is not None and len(self.events) > self.max_items:
                self.events = self.events[1:]
                continue
            if self.max_chars is not None and len(self.text()) > self.max_chars:
                self.events = self.events[1:]
                continue
            break


class SnapshotBuilder:

    @staticmethod
    def _json_clone(payload: Any) -> Any:
        return json.loads(json.dumps(payload, ensure_ascii=True))

    def _game_state_snapshot(self, orch) -> dict[str, Any]:
        return {
            "player_location": orch.game_state.player_location,
            "discovered_keys": sorted(str(value) for value in orch.game_state.discovered_keys),
            "quest_flags": dict(sorted(orch.game_state.quest_flags.items())),
            "npc_locations": dict(sorted(orch.game_state.npc_locations.items())),
            "conversation_history": self._json_clone(orch.game_state.conversation_history),
        }

    def _memory_snapshot(self, orch) -> dict[str, Any]:
        by_entity: dict[str, list[str]] = {}
        counts: list[dict[str, Any]] = []
        for entity in sorted(orch.world.entities.values(), key=lambda value: value.key.lower()):
            sentences = list(entity.memory.sentences)
            if sentences:
                by_entity[entity.key] = sentences
            counts.append(
                {
                    "entity": entity.key,
                    "entity_type": entity.entity_type,
                    "memory_count": len(sentences),
                }
            )
        return {
            "counts": counts,
            "by_entity": by_entity,
        }

    def build(self, orch):
        world = orch.world
        current_location = orch.game_state.player_location
        scene = world.scene_snapshot(current_location)
        scene_keys = {
            current_location,
            *[str(key) for key in scene.get("connections", [])],
            *[str(key) for key in scene.get("actors_here", [])],
            *[str(key) for key in scene.get("items_here", [])],
        }

        nodes = []
        for node in world.graph_nodes():
            key = str(node.get("key") or "").strip()
            if not key:
                continue
            payload = dict(node)
            payload["flags"] = {
                "current_location": key == current_location,
                "in_scene": key in scene_keys,
                "discovered": key in orch.discovered_keys or world.location_for_key(key) in orch.discovered_keys,
            }
            nodes.append(payload)

        edges = world.graph_edges()
        history = [{"role": role, "content": content} for role, content in orch.history.turns]

        return {
            "turn": orch.turn_index,
            "beat": orch.beats.current(),
            "beat_state": {
                "current_index": orch.beats.index,
                "current": orch.beats.current(),
                "next": orch.beats.next(),
                "total": len(orch.beats.beats),
            },
            "current_location": current_location,
            "scene": {
                "location": scene.get("location", current_location),
                "description": scene.get("description", ""),
                "connections": list(scene.get("connections", [])),
                "actors_here": list(scene.get("actors_here", [])),
                "items_here": list(scene.get("items_here", [])),
            },
            "session_summary": orch.summary.text(),
            "session_summary_events": list(orch.summary.events),
            "story_status": orch.story_status,
            "history": history,
            "active_keys": sorted(str(key) for key in scene_keys if str(key).strip()),
            "focus": [
                current_location,
                *[str(key) for key in scene.get("actors_here", []) if str(key).strip()],
                *[str(key) for key in scene.get("items_here", []) if str(key).strip()],
            ],
            "discovered_keys": sorted(str(value) for value in orch.discovered_keys),
            "game_state": self._game_state_snapshot(orch),
            "world_records": {
                "story": world.story_record(),
                "locations": world.list_location_records(),
                "entities": world.list_entity_records(),
                "items": world.list_item_records(),
            },
            "memory": self._memory_snapshot(orch),
            "last_turn": self._json_clone(getattr(orch, "last_turn_result", {}) or {}),
            "nodes": nodes,
            "edges": edges,
        }


def write_session_checkpoint(session_dir: Path | str, orch, turn_number: int) -> Path:
    root = Path(session_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    label = f"turn_{int(turn_number):03d}"
    snapshot_path = root / f"{label}.json"
    snapshot_path.write_text(
        json.dumps(orch.snapshot(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    save_runtime_world_checkpoint(orch.game_state, label)
    return snapshot_path


__all__ = [
    "BeatTracker",
    "SessionSummary",
    "SnapshotBuilder",
    "write_session_checkpoint",
]

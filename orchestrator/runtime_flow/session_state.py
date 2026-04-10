from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


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
            "story_status": orch.story_status,
            "history": history,
            "nodes": nodes,
            "edges": edges,
        }


__all__ = [
    "BeatTracker",
    "SessionSummary",
    "SnapshotBuilder",
]

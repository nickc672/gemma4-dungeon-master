from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Iterable, Set
import re

from ..world_state.world_model import WorldModel


# ================================
# Beat Tracker
# ================================

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


# ================================
# Session Summary
# ================================

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


# ================================
# Active Key Manager
# ================================

class ActiveKeyManager:
    MAX_ACTIVE = 14

    def refresh(
        self,
        world: WorldModel,
        current_focus: List[str],
        explicit_keys: Optional[Iterable[str]] = None,
        beat_text: str = "",
    ) -> Set[str]:
        active = world.active_context_keys(
            focus_keys=list(current_focus or []),
            explicit_keys=list(explicit_keys or []),
            limit=self.MAX_ACTIVE,
        )
        if beat_text:
            for key in world.all_keys():
                if key.lower() in beat_text.lower() and key not in active:
                    active.append(key)
                if len(active) >= self.MAX_ACTIVE:
                    break
        return set(active[: self.MAX_ACTIVE])

    def register_discovery(self, keys, discovered: Set[str], world: WorldModel):
        unlocked = []
        for k in keys:
            if k not in discovered and world.has_key(k):
                discovered.add(k)
                unlocked.append(k)
        return unlocked


# ================================
# Focus Manager
# ================================

class FocusManager:
    """Decides what story nodes should be in focus."""

    def apply_intent(
        self,
        intent: Dict[str, Any],
        current_focus: List[str],
        world: WorldModel,
    ) -> List[str]:

        action = str(intent.get("action_category") or intent.get("action") or "").lower()
        targets = [t for t in intent.get("targets", []) if world.has_key(t)]

        if targets and action in {"move", "talk", "inspect", "other"}:
            return targets[:2]

        if not current_focus and targets:
            return targets[:2]

        return current_focus

    def resolve_from_text(self, text: str, world: WorldModel) -> Optional[str]:
        lowered = text.lower()

        verb_patterns = [
            r"go to ([\w' ]+)",
            r"head to ([\w' ]+)",
            r"walk to ([\w' ]+)",
            r"move to ([\w' ]+)",
            r"enter ([\w' ]+)",
            r"to ([\w' ]+)",
        ]

        candidates = []

        for pat in verb_patterns:
            for match in re.finditer(pat, lowered):
                candidates.append(match.group(1).strip())

        for key in world.all_keys():
            if key.lower() in lowered:
                candidates.append(key)

        if not candidates:
            return None

        cand = candidates[0].lower()

        for key in world.all_keys():
            if key.lower() == cand or cand in key.lower():
                return key

        return None


# ================================
# Snapshot Builder
# ================================

class SnapshotBuilder:

    def build(self, orch):
        world = orch.world
        nodes = []
        for node in world.graph_nodes():
            key = str(node.get("key") or "").strip()
            if not key:
                continue
            payload = dict(node)
            payload["flags"] = {
                "active": key in orch.active_keys,
                "focus": key in orch.current_focus,
                "discovered": key in orch.discovered_keys or world.location_for_key(key) in orch.discovered_keys,
            }
            nodes.append(payload)

        edges = world.graph_edges()

        history = [
            {"role": r, "content": c}
            for r, c in orch.history.turns
        ]

        return {
            "turn": orch.turn_index,
            "beat": orch.beats.current(),
            "beat_state": {
                "current_index": orch.beats.index,
                "current": orch.beats.current(),
                "next": orch.beats.next(),
                "total": len(orch.beats.beats),
            },
            "active_keys": sorted(orch.active_keys),
            "focus": orch.current_focus,
            "session_summary": orch.summary.text(),
            "story_status": orch.story_status,
            "history": history,
            "nodes": nodes,
            "edges": edges,
        }


# ================================

__all__ = [
    "BeatTracker",
    "SessionSummary",
    "ActiveKeyManager",
    "FocusManager",
    "SnapshotBuilder",
]

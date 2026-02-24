from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Iterable, Set
import re


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
        story,
        current_focus: List[str],
        explicit_keys: Optional[Iterable[str]] = None,
        beat_text: str = "",
    ) -> Set[str]:

        explicit = {k for k in (explicit_keys or []) if k in story.by_key}
        focus = [k for k in current_focus if k in story.by_key]

        if not focus and story.initial_keys:
            focus = [story.initial_keys[0]]

        active: List[str] = []

        def add(k: str):
            if k and k in story.by_key and k not in active:
                active.append(k)

        for k in focus:
            add(k)

        for k in focus:
            node = story.get_node(k)
            if node:
                for n in node.connections:
                    add(n)

        for k in explicit:
            add(k)

        if beat_text:
            for k in story.by_key:
                if k.lower() in beat_text.lower():
                    add(k)

        if len(active) > self.MAX_ACTIVE:
            active = active[: self.MAX_ACTIVE]

        return set(active)

    def register_discovery(self, keys, discovered: Set[str], story):
        unlocked = []
        for k in keys:
            if k not in discovered and k in story.by_key:
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
        story,
    ) -> List[str]:

        action = str(intent.get("action_category") or intent.get("action") or "").lower()
        targets = [t for t in intent.get("targets", []) if t in story.by_key]
        refusals = set(intent.get("refusals", []))

        # Drop refused focus
        if any(f in refusals for f in current_focus):
            current_focus = []

        if targets and action in {"move", "talk", "inspect", "other"}:
            return targets[:2]

        if not current_focus and targets:
            return targets[:2]

        return current_focus

    def resolve_from_text(self, text: str, story) -> Optional[str]:
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

        for key in story.by_key:
            if key.lower() in lowered:
                candidates.append(key)

        if not candidates:
            return None

        cand = candidates[0].lower()

        for key in story.by_key:
            if key.lower() == cand or cand in key.lower():
                return key

        return None


# ================================
# Snapshot Builder
# ================================

class SnapshotBuilder:

    def build(self, orch):

        nodes = []
        for k, n in orch.story.by_key.items():
            nodes.append({
                "key": k,
                "description": n.description,
                "connections": list(n.connections),
                "flags": {
                    "active": k in orch.active_keys,
                    "focus": k in orch.current_focus,
                    "discovered": k in orch.discovered_keys,
                },
            })

        history = [
            {"role": r, "content": c}
            for r, c in orch.history.turns
        ]

        return {
            "turn": orch.turn_index,
            "beat": orch.beats.current(),
            "active_keys": sorted(orch.active_keys),
            "focus": orch.current_focus,
            "session_summary": orch.summary.text(),
            "story_status": orch.story_status,
            "history": history,
        }


# ================================

__all__ = [
    "BeatTracker",
    "SessionSummary",
    "ActiveKeyManager",
    "FocusManager",
    "SnapshotBuilder",
]

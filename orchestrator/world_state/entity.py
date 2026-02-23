from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List


DEFAULT_PLAYER_STATS: Dict[str, int] = {
    "strength": 10,
    "dexterity": 14,
    "constitution": 12,
    "intelligence": 12,
    "wisdom": 13,
    "charisma": 11,
}

DEFAULT_PLAYER_SKILLS: Dict[str, int] = {
    "perception": 2,
    "investigation": 3,
    "insight": 1,
    "stealth": 4,
    "sleight_of_hand": 4,
    "persuasion": 1,
    "deception": 1,
    "athletics": 0,
}


def _norm(text: str) -> str:
    return str(text or "").strip().lower()


def _ability_mod(score: int) -> int:
    return (int(score) - 10) // 2


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", str(text or "").lower()))


def split_into_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", str(text or ""))
    return [p.strip() for p in parts if p and p.strip()]


@dataclass
class MemoryHit:
    sentence: str
    score: float


class DynamicSentenceMemory:
    """
    PoC memory store: lexical search only.
    We keep the same interface used by tools.py.
    """

    def __init__(self) -> None:
        self.sentences: List[str] = []

    @classmethod
    def backend_status(cls) -> dict[str, Any]:
        return {
            "faiss_available": False,
            "error": "disabled in PoC entity memory (lexical search only)",
            "mode": "lexical",
        }

    def add_sentences(self, sentences: List[str]) -> None:
        for sentence in sentences:
            text = str(sentence).strip()
            if text:
                self.sentences.append(text)

    def add_memory(self, sentence: str) -> None:
        text = str(sentence).strip()
        if text:
            self.sentences.append(text)

    def search(self, query: str, top_n: int = 3) -> List[MemoryHit]:
        if not self.sentences:
            return []

        q = str(query or "").strip().lower()
        q_tokens = _tokens(q)
        hits: List[MemoryHit] = []

        for sentence in self.sentences:
            s_lower = sentence.lower()
            s_tokens = _tokens(sentence)
            overlap = len(q_tokens & s_tokens)
            union = len(q_tokens | s_tokens) or 1
            score = overlap / union
            if q and q in s_lower:
                score += 0.5
            if overlap > 0 or (q and q in s_lower):
                hits.append(MemoryHit(sentence=sentence, score=float(score)))

        if not hits:
            recent = list(reversed(self.sentences[-max(1, int(top_n)) :]))
            return [MemoryHit(sentence=s, score=0.0) for s in recent]

        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[: max(1, int(top_n))]


@dataclass
class Entity:
    key: str
    name: str
    entity_type: str
    description: str
    location: str
    skills: Dict[str, int] = field(default_factory=dict)
    stats: Dict[str, int] = field(default_factory=dict)
    memory: DynamicSentenceMemory = field(default_factory=DynamicSentenceMemory)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_location(self) -> str:
        return self.location

    def set_location(self, location: str) -> None:
        self.location = str(location or "unknown")

    def get_skill(self, skill: str, default: int | None = None) -> int | None:
        return self.skills.get(_norm(skill).replace(" ", "_"), default)

    def get_stat_modifier(self, stat: str | None) -> int:
        if not stat:
            return 0
        score = self.stats.get(_norm(stat), 10)
        return _ability_mod(score)

    def add_memory(self, text: str) -> None:
        self.memory.add_memory(text)

    def search_memory(self, query: str, top_n: int = 3) -> List[MemoryHit]:
        return self.memory.search(query, top_n=top_n)

    @property
    def memory_count(self) -> int:
        return len(self.memory.sentences)

    def list_skill_names(self) -> List[str]:
        return sorted(self.skills.keys())

    def to_public_view(self, *, include_memory_preview: bool = False, memory_preview: int = 3) -> dict[str, Any]:
        payload = {
            "key": self.key,
            "name": self.name,
            "entity_type": self.entity_type,
            "description": self.description,
            "location": self.location,
            "skills": dict(self.skills),
            "stats": dict(self.stats),
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "memory_count": self.memory_count,
        }
        if include_memory_preview:
            payload["memory_preview"] = list(self.memory.sentences[-max(0, int(memory_preview)) :])
        return payload


__all__ = [
    "DEFAULT_PLAYER_SKILLS",
    "DEFAULT_PLAYER_STATS",
    "DynamicSentenceMemory",
    "Entity",
    "MemoryHit",
    "split_into_sentences",
]

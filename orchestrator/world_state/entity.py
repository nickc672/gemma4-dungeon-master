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
class BaseEntity:
    key: str
    name: str
    entity_type: str
    description: str
    memory: DynamicSentenceMemory = field(default_factory=DynamicSentenceMemory, kw_only=True)
    tags: List[str] = field(default_factory=list, kw_only=True)

    @property
    def type(self) -> str:
        return self.entity_type

    @type.setter
    def type(self, value: str) -> None:
        self.entity_type = _norm(value) or "entity"

    def add_memory(self, text: str) -> None:
        self.memory.add_memory(text)

    def search_memory(self, query: str, top_n: int = 3) -> List[MemoryHit]:
        return self.memory.search(query, top_n=top_n)

    @property
    def memory_count(self) -> int:
        return len(self.memory.sentences)

    def get_skill(self, skill: str, default: int | None = None) -> int | None:
        _ = skill
        return default

    def get_stat_modifier(self, stat: str | None) -> int:
        _ = stat
        return 0

    def list_skill_names(self) -> List[str]:
        return []

    def _base_record(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "tags": list(self.tags),
            "memory": list(self.memory.sentences),
        }

    def _load_memory_lines(self, payload: dict[str, Any]) -> None:
        for memory_line in payload.get("memory") or []:
            text = str(memory_line).strip()
            if text:
                self.add_memory(text)

    def to_record(self) -> dict[str, Any]:
        return self._base_record()

    def to_public_view(self, *, include_memory_preview: bool = False, memory_preview: int = 3) -> dict[str, Any]:
        payload = {
            "key": self.key,
            "name": self.name,
            "type": self.type,
            "entity_type": self.entity_type,
            "description": self.description,
            "tags": list(self.tags),
            "memory_count": self.memory_count,
        }
        if include_memory_preview:
            payload["memory_preview"] = list(self.memory.sentences[-max(0, int(memory_preview)) :])
        return payload


@dataclass
class Entity(BaseEntity):
    location: str
    inventory: List[str] = field(default_factory=list)
    skills: Dict[str, int] = field(default_factory=dict)
    stats: Dict[str, int] = field(default_factory=dict)

    def get_location(self) -> str:
        return self.location

    def set_location(self, location: str) -> None:
        self.location = str(location or "unknown")

    def add_item(self, item_key: str) -> None:
        key = str(item_key or "").strip()
        if key and key not in self.inventory:
            self.inventory.append(key)

    def remove_item(self, item_key: str) -> None:
        key = str(item_key or "").strip()
        if not key:
            return
        self.inventory = [existing for existing in self.inventory if existing != key]

    def has_item(self, item_key: str) -> bool:
        key = str(item_key or "").strip()
        return bool(key) and key in self.inventory

    def get_skill(self, skill: str, default: int | None = None) -> int | None:
        return self.skills.get(_norm(skill).replace(" ", "_"), default)

    def get_stat_modifier(self, stat: str | None) -> int:
        if not stat:
            return 0
        score = self.stats.get(_norm(stat), 10)
        return _ability_mod(score)

    def list_skill_names(self) -> List[str]:
        return sorted(self.skills.keys())

    def to_record(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "type": self.type,
            "entity_type": self.entity_type,
            "description": self.description,
            "location": self.location,
            "skills": dict(self.skills),
            "stats": dict(self.stats),
            "tags": list(self.tags),
            "memory": list(self.memory.sentences),
        }

    @classmethod
    def from_record(cls, payload: dict[str, Any]) -> "Entity":
        entity_type = str(payload.get("entity_type") or payload.get("type") or "npc").strip().lower() or "npc"
        if entity_type == "player":
            return Player.from_record(payload)
        skills = payload.get("skills") or {}
        stats = payload.get("stats") or {}
        entity = cls(
            key=str(payload["key"]),
            name=str(payload.get("name") or payload["key"]),
            entity_type=entity_type,
            description=str(payload.get("description") or ""),
            location=str(payload.get("location") or "unknown"),
            skills=dict(skills) if isinstance(skills, dict) else {},
            stats=dict(stats) if isinstance(stats, dict) else {},
            tags=[str(tag) for tag in payload.get("tags") or []],
        )
        entity._load_memory_lines(payload)
        return entity

    def to_public_view(self, *, include_memory_preview: bool = False, memory_preview: int = 3) -> dict[str, Any]:
        payload = super().to_public_view(
            include_memory_preview=include_memory_preview,
            memory_preview=memory_preview,
        )
        payload.update(
            {
                "location": self.location,
                "inventory": list(self.inventory),
                "skills": dict(self.skills),
                "stats": dict(self.stats),
            }
        )
        return payload


@dataclass
class Player(Entity):
    entity_type: str = field(default="player", init=False)

    def __post_init__(self) -> None:
        self.entity_type = "player"
        if not self.skills:
            self.skills = dict(DEFAULT_PLAYER_SKILLS)
        if not self.stats:
            self.stats = dict(DEFAULT_PLAYER_STATS)
        if "player" not in self.tags:
            self.tags.append("player")

    @classmethod
    def from_record(cls, payload: dict[str, Any]) -> "Player":
        skills = payload.get("skills") or {}
        stats = payload.get("stats") or {}
        player = cls(
            key=str(payload["key"]),
            name=str(payload.get("name") or payload["key"]),
            description=str(payload.get("description") or ""),
            location=str(payload.get("location") or "unknown"),
            skills=dict(skills) if isinstance(skills, dict) else {},
            stats=dict(stats) if isinstance(stats, dict) else {},
            tags=[str(tag) for tag in payload.get("tags") or []],
        )
        player._load_memory_lines(payload)
        return player


__all__ = [
    "BaseEntity",
    "DEFAULT_PLAYER_SKILLS",
    "DEFAULT_PLAYER_STATS",
    "DynamicSentenceMemory",
    "Entity",
    "MemoryHit",
    "Player",
    "split_into_sentences",
]

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List


@dataclass
class Item:
    key: str
    name: str
    description: str
    holder_kind: str
    holder_key: str
    portable: bool = True
    tags: List[str] = field(default_factory=list)

    def set_holder(self, holder_kind: str, holder_key: str) -> None:
        self.holder_kind = str(holder_kind or "unknown").strip().lower() or "unknown"
        self.holder_key = str(holder_key or "unknown").strip() or "unknown"

    def is_at_location(self, location_key: str) -> bool:
        return self.holder_kind == "location" and self.holder_key == str(location_key or "").strip()

    def is_held_by(self, entity_key: str) -> bool:
        return self.holder_kind == "entity" and self.holder_key == str(entity_key or "").strip()

    def to_record(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "holder_kind": self.holder_kind,
            "holder_key": self.holder_key,
            "portable": bool(self.portable),
            "tags": list(self.tags),
        }

    @classmethod
    def from_record(cls, payload: dict[str, Any]) -> "Item":
        return cls(
            key=str(payload["key"]),
            name=str(payload.get("name") or payload["key"]),
            description=str(payload.get("description") or ""),
            holder_kind=str(payload.get("holder_kind") or "location").strip().lower() or "location",
            holder_key=str(payload.get("holder_key") or "unknown").strip() or "unknown",
            portable=bool(payload.get("portable", True)),
            tags=[str(tag) for tag in payload.get("tags") or []],
        )


__all__ = ["Item"]

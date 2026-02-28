from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List


@dataclass
class Location:
    key: str
    name: str
    description: str
    connections: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    def is_connected_to(self, location_key: str) -> bool:
        return str(location_key or "").strip() in self.connections

    def connect(self, location_key: str) -> None:
        key = str(location_key or "").strip()
        if key and key not in self.connections:
            self.connections.append(key)

    def disconnect(self, location_key: str) -> None:
        key = str(location_key or "").strip()
        if not key:
            return
        self.connections = [existing for existing in self.connections if existing != key]

    def to_record(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "connections": list(self.connections),
            "tags": list(self.tags),
        }

    @classmethod
    def from_record(cls, payload: dict[str, Any]) -> "Location":
        return cls(
            key=str(payload["key"]),
            name=str(payload.get("name") or payload["key"]),
            description=str(payload.get("description") or ""),
            connections=[str(connection) for connection in payload.get("connections") or []],
            tags=[str(tag) for tag in payload.get("tags") or []],
        )


__all__ = ["Location"]

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List

from .entity import BaseEntity


@dataclass
class Location(BaseEntity):
    entity_type: str = field(default="location", init=False)
    connections: List[str] = field(default_factory=list)

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
        payload = self._base_record()
        payload["connections"] = list(self.connections)
        return payload

    @classmethod
    def from_record(cls, payload: dict[str, Any]) -> "Location":
        location = cls(
            key=str(payload["key"]),
            name=str(payload.get("name") or payload["key"]),
            description=str(payload.get("description") or ""),
            connections=[str(connection) for connection in payload.get("connections") or []],
            tags=[str(tag) for tag in payload.get("tags") or []],
        )
        location._load_memory_lines(payload)
        return location


__all__ = ["Location"]

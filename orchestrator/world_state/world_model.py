from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .entity import Entity
from .item import Item
from .location import Location


WORLD_MODEL_DATA_DIR = Path(__file__).resolve().parent / "data" / "world_model"


def _normalize_key(text: str) -> str:
    return str(text or "").strip().lower()


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)
        handle.write("\n")


def _load_json_sequence(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array.")
    return [entry for entry in payload if isinstance(entry, dict)]


def _load_json_mapping(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return payload


def resolve_world_model_data_dir(data_dir: Path | str | None = None) -> Path:
    if data_dir is None:
        return WORLD_MODEL_DATA_DIR
    return Path(data_dir).expanduser().resolve()


@dataclass
class WorldModel:
    locations: Dict[str, Location] = field(default_factory=dict)
    entities: Dict[str, Entity] = field(default_factory=dict)
    items: Dict[str, Item] = field(default_factory=dict)
    beat_list: List[str] = field(default_factory=list)
    starting_location: str = ""
    starting_state: str = ""

    def add_location(self, location: Location) -> None:
        self.locations[_normalize_key(location.key)] = location

    def add_entity(self, entity: Entity) -> None:
        self.entities[_normalize_key(entity.key)] = entity

    def add_item(self, item: Item) -> None:
        self.items[_normalize_key(item.key)] = item

    def get_location(self, key: str) -> Optional[Location]:
        return self.locations.get(_normalize_key(key))

    def get_entity(self, key: str) -> Optional[Entity]:
        return self.entities.get(_normalize_key(key))

    def get_item(self, key: str) -> Optional[Item]:
        return self.items.get(_normalize_key(key))

    def has_key(self, key: str) -> bool:
        return (
            self.get_location(key) is not None
            or self.get_entity(key) is not None
            or self.get_item(key) is not None
        )

    def all_keys(self) -> list[str]:
        keys = [
            *(location.key for location in self.locations.values()),
            *(entity.key for entity in self.entities.values()),
            *(item.key for item in self.items.values()),
        ]
        return sorted(keys, key=str.lower)

    def key_kind(self, key: str) -> str:
        if self.get_location(key) is not None:
            return "location"
        entity = self.get_entity(key)
        if entity is not None:
            return entity.entity_type
        if self.get_item(key) is not None:
            return "item"
        return ""

    def location_for_key(self, key: str) -> str:
        location = self.get_location(key)
        if location is not None:
            return location.key

        entity = self.get_entity(key)
        if entity is not None:
            return entity.location

        item = self.get_item(key)
        if item is None:
            return ""
        if item.holder_kind == "location":
            return item.holder_key
        if item.holder_kind == "entity":
            holder = self.get_entity(item.holder_key)
            if holder is not None:
                return holder.location
        return ""

    def list_location_records(self) -> list[dict[str, Any]]:
        return [location.to_record() for location in sorted(self.locations.values(), key=lambda value: value.key.lower())]

    def list_entity_records(self, entity_type: str | None = None) -> list[dict[str, Any]]:
        normalized_type = str(entity_type or "").strip().lower()
        records: list[dict[str, Any]] = []
        for entity in sorted(self.entities.values(), key=lambda value: value.key.lower()):
            if normalized_type and entity.entity_type != normalized_type:
                continue
            records.append(entity.to_record())
        return records

    def list_item_records(self, holder_kind: str | None = None, holder_key: str | None = None) -> list[dict[str, Any]]:
        normalized_kind = str(holder_kind or "").strip().lower()
        normalized_key = str(holder_key or "").strip()
        records: list[dict[str, Any]] = []
        for item in sorted(self.items.values(), key=lambda value: value.key.lower()):
            if normalized_kind and item.holder_kind != normalized_kind:
                continue
            if normalized_key and item.holder_key != normalized_key:
                continue
            records.append(item.to_record())
        return records

    def actors_at(self, location_key: str) -> List[Entity]:
        key = str(location_key or "").strip()
        return [entity for entity in self.entities.values() if entity.get_location() == key]

    def items_at(self, location_key: str) -> List[Item]:
        key = str(location_key or "").strip()
        return [item for item in self.items.values() if item.is_at_location(key)]

    def items_held_by(self, entity_key: str) -> List[Item]:
        key = str(entity_key or "").strip()
        return [item for item in self.items.values() if item.is_held_by(key)]

    def set_story(
        self,
        *,
        starting_location: str | None = None,
        starting_state: str | None = None,
        beat_list: list[str] | None = None,
    ) -> None:
        if starting_location is not None:
            self.starting_location = str(starting_location).strip()
        if starting_state is not None:
            self.starting_state = str(starting_state).strip()
        if beat_list is not None:
            self.beat_list = [str(beat).strip() for beat in beat_list if str(beat).strip()]

    def connect_locations(self, location_key: str, other_location_key: str, *, bidirectional: bool = True) -> bool:
        location = self.get_location(location_key)
        other = self.get_location(other_location_key)
        if location is None or other is None:
            return False
        location.connect(other.key)
        if bidirectional:
            other.connect(location.key)
        return True

    def disconnect_locations(self, location_key: str, other_location_key: str, *, bidirectional: bool = True) -> bool:
        location = self.get_location(location_key)
        other = self.get_location(other_location_key)
        if location is None or other is None:
            return False
        location.disconnect(other.key)
        if bidirectional:
            other.disconnect(location.key)
        return True

    def move_entity(self, entity_key: str, location_key: str) -> bool:
        entity = self.get_entity(entity_key)
        location = self.get_location(location_key)
        if entity is None or location is None:
            return False
        entity.set_location(location.key)
        return True

    def move_item_to_location(self, item_key: str, location_key: str) -> bool:
        item = self.get_item(item_key)
        location = self.get_location(location_key)
        if item is None or location is None:
            return False
        item.set_holder("location", location.key)
        self.sync_actor_inventories()
        return True

    def move_item_to_entity(self, item_key: str, entity_key: str) -> bool:
        item = self.get_item(item_key)
        entity = self.get_entity(entity_key)
        if item is None or entity is None:
            return False
        item.set_holder("entity", entity.key)
        self.sync_actor_inventories()
        return True

    def sync_actor_inventories(self) -> None:
        for entity in self.entities.values():
            entity.inventory = []
        for item in self.items.values():
            if item.holder_kind != "entity":
                continue
            holder = self.get_entity(item.holder_key)
            if holder is not None:
                holder.add_item(item.key)

    def scene_snapshot(self, location_key: str) -> dict[str, object]:
        location = self.get_location(location_key)
        if location is None:
            return {
                "location": str(location_key or "").strip(),
                "description": "Unknown location",
                "connections": [],
                "actors_here": [],
                "items_here": [],
            }
        return {
            "location": location.key,
            "description": location.description,
            "connections": list(location.connections),
            "actors_here": [entity.key for entity in self.actors_at(location.key)],
            "items_here": [item.key for item in self.items_at(location.key)],
        }

    def active_context_keys(self, focus_keys: list[str], explicit_keys: list[str] | None = None, limit: int = 14) -> list[str]:
        focus = [key for key in focus_keys if self.has_key(key)]
        if not focus and self.starting_location:
            focus = [self.starting_location]

        active: list[str] = []

        def add(key: str) -> None:
            cleaned = str(key or "").strip()
            if cleaned and self.has_key(cleaned) and cleaned not in active:
                active.append(cleaned)

        for key in focus:
            add(key)

        location_key = self.location_for_key(focus[0]) if focus else self.starting_location
        if location_key:
            scene = self.scene_snapshot(location_key)
            add(str(scene.get("location") or ""))
            for key in scene.get("connections", []):
                add(str(key))
            for key in scene.get("actors_here", []):
                add(str(key))
            for key in scene.get("items_here", []):
                add(str(key))

        for key in explicit_keys or []:
            add(key)

        return active[: max(1, int(limit))]

    def graph_nodes(self) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for location in sorted(self.locations.values(), key=lambda value: value.key.lower()):
            nodes.append(
                {
                    "key": location.key,
                    "kind": "location",
                    "description": location.description,
                    "location": location.key,
                }
            )
        for entity in sorted(self.entities.values(), key=lambda value: value.key.lower()):
            nodes.append(
                {
                    "key": entity.key,
                    "kind": entity.entity_type,
                    "description": entity.description,
                    "location": entity.location,
                }
            )
        for item in sorted(self.items.values(), key=lambda value: value.key.lower()):
            nodes.append(
                {
                    "key": item.key,
                    "kind": "item",
                    "description": item.description,
                    "location": self.location_for_key(item.key),
                    "holder_kind": item.holder_kind,
                    "holder_key": item.holder_key,
                }
            )
        return nodes

    def graph_edges(self) -> list[dict[str, str]]:
        edges: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def add(src: str, dst: str) -> None:
            if not src or not dst or src == dst:
                return
            edge = tuple(sorted((src, dst)))
            if edge in seen:
                return
            seen.add(edge)
            edges.append({"src": src, "dst": dst})

        for location in self.locations.values():
            for connection in location.connections:
                if self.get_location(connection) is not None:
                    add(location.key, connection)

        for entity in self.entities.values():
            if self.get_location(entity.location) is not None:
                add(entity.key, entity.location)

        for item in self.items.values():
            if item.holder_kind == "location" and self.get_location(item.holder_key) is not None:
                add(item.key, item.holder_key)
            elif item.holder_kind == "entity" and self.get_entity(item.holder_key) is not None:
                add(item.key, item.holder_key)

        return edges

    def story_record(self) -> dict[str, Any]:
        return {
            "starting_location": self.starting_location,
            "starting_state": self.starting_state,
            "beat_list": list(self.beat_list),
        }

    def validate(self) -> list[str]:
        errors: list[str] = []

        if self.starting_location and self.get_location(self.starting_location) is None:
            errors.append(f"Starting location '{self.starting_location}' does not exist.")

        for location in self.locations.values():
            for connection in location.connections:
                if self.get_location(connection) is None:
                    errors.append(f"Location '{location.key}' connects to unknown location '{connection}'.")

        for entity in self.entities.values():
            if self.get_location(entity.location) is None:
                errors.append(f"Entity '{entity.key}' is at unknown location '{entity.location}'.")

        for item in self.items.values():
            if item.holder_kind == "location" and self.get_location(item.holder_key) is None:
                errors.append(f"Item '{item.key}' points to unknown location holder '{item.holder_key}'.")
            elif item.holder_kind == "entity" and self.get_entity(item.holder_key) is None:
                errors.append(f"Item '{item.key}' points to unknown entity holder '{item.holder_key}'.")
            elif item.holder_kind not in {"location", "entity"}:
                errors.append(f"Item '{item.key}' has unsupported holder kind '{item.holder_kind}'.")

        return errors

    def save(self, data_dir: Path | str | None = None) -> None:
        base_dir = resolve_world_model_data_dir(data_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        _write_json(base_dir / "story.json", self.story_record())
        _write_json(base_dir / "locations.json", self.list_location_records())
        _write_json(base_dir / "actors.json", self.list_entity_records())
        _write_json(base_dir / "items.json", self.list_item_records())

    def save_checkpoint(self, checkpoint_root: Path | str, checkpoint_name: str = "") -> Path:
        root = Path(checkpoint_root).expanduser().resolve()
        label = str(checkpoint_name or "").strip() or "latest"
        destination = root / label / "world_model"
        self.save(destination)
        return destination

    @classmethod
    def load(cls, data_dir: Path | str | None = None) -> "WorldModel":
        base_dir = resolve_world_model_data_dir(data_dir)
        story_payload = _load_json_mapping(base_dir / "story.json")
        location_payloads = _load_json_sequence(base_dir / "locations.json")
        actor_payloads = _load_json_sequence(base_dir / "actors.json")
        item_payloads = _load_json_sequence(base_dir / "items.json")

        model = cls(
            beat_list=[str(beat).strip() for beat in story_payload.get("beat_list") or [] if str(beat).strip()],
            starting_location=str(story_payload.get("starting_location") or "").strip(),
            starting_state=str(story_payload.get("starting_state") or "").strip(),
        )

        for payload in location_payloads:
            model.add_location(Location.from_record(payload))

        default_location = model.starting_location
        if not default_location and model.locations:
            default_location = next(iter(model.locations.values())).key

        for payload in actor_payloads:
            entity_payload = dict(payload)
            if default_location and not entity_payload.get("location"):
                entity_payload["location"] = default_location
            model.add_entity(Entity.from_record(entity_payload))

        for payload in item_payloads:
            model.add_item(Item.from_record(payload))

        model.sync_actor_inventories()
        return model


def build_world_model(data_dir: Path | str | None = None) -> WorldModel:
    return WorldModel.load(data_dir=data_dir)


__all__ = ["WORLD_MODEL_DATA_DIR", "WorldModel", "build_world_model", "resolve_world_model_data_dir"]

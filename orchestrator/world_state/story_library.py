from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .world_model import WORLD_MODEL_DATA_DIR


STORY_LIBRARY_DIR = Path(__file__).resolve().parent / "data" / "stories"
REQUIRED_WORLD_MODEL_FILES = ("story.json", "locations.json", "actors.json", "items.json")


@dataclass(frozen=True)
class StorySource:
    key: str
    label: str
    data_dir: Path
    starting_location: str = ""
    description: str = ""
    legacy: bool = False


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").strip().lower()).strip("-")
    return slug or "story"


def _is_world_model_dir(path: Path) -> bool:
    return path.is_dir() and all((path / filename).is_file() for filename in REQUIRED_WORLD_MODEL_FILES)


def _read_story_record(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads((path / "story.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _label_from_story(path: Path, story: dict[str, Any]) -> str:
    title = str(story.get("title") or "").strip()
    if title:
        return title
    name = path.name.replace("-", " ").replace("_", " ").strip()
    return name.title() if name else "Untitled Story"


def _description_from_story(story: dict[str, Any]) -> str:
    description = str(story.get("description") or story.get("synopsis") or "").strip()
    if description:
        return description
    starting_state = " ".join(str(story.get("starting_state") or "").split()).strip()
    if len(starting_state) > 160:
        return starting_state[:160].rstrip() + "..."
    return starting_state


def story_source_from_dir(path: Path, *, key: str = "", legacy: bool = False) -> StorySource | None:
    source_dir = path.expanduser().resolve()
    if not _is_world_model_dir(source_dir):
        return None
    story = _read_story_record(source_dir)
    source_key = key or _slugify(source_dir.name)
    return StorySource(
        key=source_key,
        label=_label_from_story(source_dir, story),
        data_dir=source_dir,
        starting_location=str(story.get("starting_location") or "").strip(),
        description=_description_from_story(story),
        legacy=legacy,
    )


def list_story_sources() -> list[StorySource]:
    sources: list[StorySource] = []
    if STORY_LIBRARY_DIR.is_dir():
        for story_dir in sorted(STORY_LIBRARY_DIR.iterdir(), key=lambda path: path.name.lower()):
            source = story_source_from_dir(story_dir)
            if source is not None:
                sources.append(source)

    legacy_source = story_source_from_dir(WORLD_MODEL_DATA_DIR, key="default-world-model", legacy=True)
    if legacy_source is not None and not sources:
        sources.append(legacy_source)
    return sources


def get_story_source(key: str) -> StorySource:
    sources = list_story_sources()
    for source in sources:
        if source.key == key:
            return source
    if sources:
        return sources[0]
    raise FileNotFoundError(
        f"No story sources found. Expected {', '.join(REQUIRED_WORLD_MODEL_FILES)} in {STORY_LIBRARY_DIR}."
    )


__all__ = [
    "REQUIRED_WORLD_MODEL_FILES",
    "STORY_LIBRARY_DIR",
    "StorySource",
    "get_story_source",
    "list_story_sources",
    "story_source_from_dir",
]

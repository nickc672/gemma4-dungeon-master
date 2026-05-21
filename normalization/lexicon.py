from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

if False:  # pragma: no cover
    from orchestrator.world_state.world_model import WorldModel


@dataclass(frozen=True)
class Concept:
    concept_type: str
    concept_id: str
    canonical_text: str
    aliases: Tuple[str, ...]


@dataclass(frozen=True)
class LexiconRecord:
    concept_type: str
    concept_id: str
    canonical_text: str
    aliases: Sequence[str]


@dataclass
class Lexicon:
    concepts: List[Concept]

    def __post_init__(self) -> None:
        self.by_id: Dict[str, Concept] = {concept.concept_id: concept for concept in self.concepts}
        self.by_canonical: Dict[str, Concept] = {concept.canonical_text.lower(): concept for concept in self.concepts}
        self.alias_to_ids: Dict[str, List[str]] = {}
        for concept in self.concepts:
            for alias in concept.aliases:
                norm = normalize_surface(alias)
                if not norm:
                    continue
                self.alias_to_ids.setdefault(norm, [])
                if concept.concept_id not in self.alias_to_ids[norm]:
                    self.alias_to_ids[norm].append(concept.concept_id)
        for ids in self.alias_to_ids.values():
            ids.sort()

    @classmethod
    def from_records(cls, records: Sequence[LexiconRecord]) -> "Lexicon":
        concepts: List[Concept] = []
        for rec in records:
            aliases = tuple(_dedupe_preserve([rec.canonical_text, *rec.aliases]))
            concepts.append(
                Concept(
                    concept_type=rec.concept_type,
                    concept_id=rec.concept_id,
                    canonical_text=rec.canonical_text,
                    aliases=aliases,
                )
            )
        return cls(concepts=sorted(concepts, key=lambda c: c.concept_id))

    @classmethod
    def from_world_model(
        cls,
        world: "WorldModel",
        *,
        lexicon_path: Optional[Path] = None,
    ) -> "Lexicon":
        """Build a Lexicon from a WorldModel instance plus the external lexicon JSON."""
        external = load_lexicon_data(lexicon_path)
        records: List[LexiconRecord] = []

        for key in sorted(world.all_keys()):
            concept_type = world.key_kind(key) or infer_story_concept_type(key)
            records.append(LexiconRecord(
                concept_type=concept_type,
                concept_id=make_concept_id(concept_type, key),
                canonical_text=key,
                aliases=[],
            ))

        for item in external.get("actions", []):
            rec = _record_from_external(item, fallback_type="action")
            if rec:
                records.append(rec)

        for item in external.get("abilities", []):
            rec = _record_from_external(item, fallback_type="ability")
            if rec:
                records.append(rec)

        for item in external.get("entities", []):
            rec = _record_from_external(item, fallback_type="entity")
            if rec:
                records.append(rec)

        return cls.from_records(_merge_records(records))


def tokenize_with_spans(text: str) -> List[Dict[str, object]]:
    tokens: List[Dict[str, object]] = []
    for match in re.finditer(r"[A-Za-z0-9']+", text):
        raw = match.group(0)
        norm = re.sub(r"[^a-z0-9']", "", raw.lower()).strip("'")
        if not norm:
            continue
        tokens.append(
            {
                "token": norm,
                "start": match.start(),
                "end": match.end(),
                "raw": raw,
            }
        )
    return tokens


def normalize_surface(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9'\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_surface_tokens(text: str) -> Tuple[str, ...]:
    surface = normalize_surface(text)
    if not surface:
        return tuple()
    return tuple(tok for tok in surface.split(" ") if tok)


def infer_story_concept_type(key: str) -> str:
    lowered = key.lower()

    item_markers = {
        "coin",
        "beads",
        "notice",
        "spyglass",
        "rope",
        "ledger",
        "knife",
        "charm",
        "scrap",
        "signet",
    }
    npc_markers = {
        "guard",
        "captain",
        "mayor",
        "scribe",
        "cleric",
        "novice",
        "wizard",
        "dockmaster",
        "deckhand",
        "smuggler",
        "fishmonger",
        "seller",
        "performer",
        "crier",
        "fisher",
        "boatman",
        "caretaker",
        "cook",
        "watcher",
        "fence",
    }
    known_npcs = {
        "mitch",
        "mara",
        "brin",
        "edda",
        "thom",
        "lysa",
        "jessa",
        "jorin",
        "ren",
        "hara",
        "finn",
        "kesh",
        "lia",
        "tellan",
        "varr",
        "pip",
        "caris",
        "ilya",
        "rian",
        "mira",
        "arlen",
        "brenna",
        "sol",
        "jaro",
        "nima",
        "talo",
        "serah",
        "arel",
        "elric",
        "loth",
    }

    if any(marker in lowered for marker in item_markers):
        return "item"
    if any(marker in lowered for marker in npc_markers):
        return "npc"
    first = lowered.split(" ")[0] if lowered else ""
    if first in known_npcs or lowered in known_npcs:
        return "npc"
    return "location"


def make_concept_id(concept_type: str, canonical_text: str) -> str:
    prefix = {
        "action": "ACT",
        "ability": "ABIL",
        "location": "LOC",
        "item": "ITEM",
        "npc": "NPC",
        "entity": "ENT",
    }.get(concept_type, "ENT")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", canonical_text).strip("_").upper()
    return f"{prefix}_{slug}" if slug else prefix


def load_lexicon_data(lexicon_path: Optional[Path]) -> Mapping[str, object]:
    path = lexicon_path or Path(__file__).resolve().parent.parent / "data" / "normalization_lexicon.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return raw


def _dedupe_preserve(values: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        cleaned = str(value).strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _merge_records(records: List[LexiconRecord]) -> List[LexiconRecord]:
    """Deduplicate records by concept_id, merging aliases."""
    merged: Dict[str, LexiconRecord] = {}
    for rec in records:
        existing = merged.get(rec.concept_id)
        if existing:
            aliases = _dedupe_preserve([*existing.aliases, *rec.aliases, rec.canonical_text])
            merged[rec.concept_id] = LexiconRecord(
                concept_type=existing.concept_type,
                concept_id=existing.concept_id,
                canonical_text=existing.canonical_text,
                aliases=aliases,
            )
        else:
            merged[rec.concept_id] = LexiconRecord(
                concept_type=rec.concept_type,
                concept_id=rec.concept_id,
                canonical_text=rec.canonical_text,
                aliases=_dedupe_preserve([*rec.aliases, rec.canonical_text]),
            )
    return list(merged.values())


def _record_from_external(item: object, *, fallback_type: str) -> Optional[LexiconRecord]:
    if not isinstance(item, dict):
        return None
    canonical = str(item.get("canonical_text") or "").strip()
    if not canonical:
        return None
    concept_type = str(item.get("concept_type") or fallback_type).strip().lower()
    if concept_type == "entity":
        concept_type = infer_story_concept_type(canonical)
    concept_id = str(item.get("concept_id") or make_concept_id(concept_type, canonical)).strip()
    if not concept_id:
        return None
    aliases = [str(alias).strip() for alias in item.get("aliases", []) if str(alias).strip()]
    return LexiconRecord(
        concept_type=concept_type,
        concept_id=concept_id,
        canonical_text=canonical,
        aliases=aliases,
    )

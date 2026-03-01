from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

from orchestrator.normalization.lexicon import normalize_surface


@dataclass(frozen=True)
class SynonymEntry:
    phrase: str
    frequency: float


class SynonymStore:
    """
    Storage-backed synonym dictionary.

    Data file format:
    {
      "phrases": {
        "enter": [{"phrase": "walk into", "frequency": 6.9}, ...],
        ...
      }
    }
    """

    def __init__(self, phrase_map: Mapping[str, Sequence[SynonymEntry]]) -> None:
        self._phrase_map: Dict[str, List[SynonymEntry]] = {
            normalize_surface(key): sorted(list(values), key=lambda item: item.frequency, reverse=True)
            for key, values in phrase_map.items()
            if normalize_surface(key)
        }
        self._reverse_map: Dict[str, List[SynonymEntry]] = {}
        for canonical, entries in self._phrase_map.items():
            for entry in entries:
                key = normalize_surface(entry.phrase)
                if not key:
                    continue
                self._reverse_map.setdefault(key, [])
                self._reverse_map[key].append(SynonymEntry(phrase=canonical, frequency=entry.frequency))
        for key, entries in self._reverse_map.items():
            self._reverse_map[key] = sorted(entries, key=lambda item: item.frequency, reverse=True)

    @classmethod
    def from_json_path(cls, path: Optional[Path] = None) -> "SynonymStore":
        file_path = path or Path(__file__).resolve().parent.parent / "data" / "synonym_store.json"
        if not file_path.exists():
            return cls({})
        try:
            raw = json.loads(file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls({})
        phrases = raw.get("phrases", {}) if isinstance(raw, dict) else {}
        phrase_map: Dict[str, List[SynonymEntry]] = {}
        if isinstance(phrases, dict):
            for canonical, entries in phrases.items():
                if not isinstance(entries, list):
                    continue
                parsed: List[SynonymEntry] = []
                for item in entries:
                    if not isinstance(item, dict):
                        continue
                    phrase = normalize_surface(str(item.get("phrase") or ""))
                    if not phrase:
                        continue
                    try:
                        frequency = float(item.get("frequency", 0.0))
                    except (TypeError, ValueError):
                        frequency = 0.0
                    parsed.append(SynonymEntry(phrase=phrase, frequency=frequency))
                phrase_map[normalize_surface(str(canonical))] = parsed
        return cls(phrase_map)

    def top_for_phrase(self, phrase: str, *, top_n: int = 20) -> List[SynonymEntry]:
        key = normalize_surface(phrase)
        if not key:
            return []
        return list(self._phrase_map.get(key, []))[:top_n]

    def reverse_for_phrase(self, phrase: str, *, top_n: int = 20) -> List[SynonymEntry]:
        key = normalize_surface(phrase)
        if not key:
            return []
        return list(self._reverse_map.get(key, []))[:top_n]

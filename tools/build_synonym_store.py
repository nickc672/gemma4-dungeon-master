from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

try:
    from nltk.corpus import wordnet as wn  # type: ignore
except Exception:  # pragma: no cover
    wn = None

try:
    from wordfreq import zipf_frequency  # type: ignore
except Exception:  # pragma: no cover
    zipf_frequency = None


ROOT = Path(__file__).resolve().parents[1]
LEXICON_PATH = ROOT / "orchestrator" / "data" / "normalization_lexicon.json"
OUT_PATH = ROOT / "orchestrator" / "data" / "synonym_store.generated.json"


def main() -> None:
    if not LEXICON_PATH.exists():
        raise SystemExit(f"Missing lexicon file: {LEXICON_PATH}")

    lexicon = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
    phrases: Dict[str, List[Dict[str, float]]] = {}

    for section in ("actions", "abilities", "entities"):
        for item in lexicon.get(section, []):
            canonical = normalize(item.get("canonical_text", ""))
            if not canonical:
                continue
            aliases = [normalize(alias) for alias in item.get("aliases", []) if normalize(alias)]
            candidates = set(aliases)
            candidates.update(fetch_wordnet_equivalents(canonical))
            ranked = rank_candidates(canonical, candidates)
            phrases[canonical] = ranked

    payload = {
        "meta": {
            "generated_by": "tools/build_synonym_store.py",
            "wordnet_available": bool(wn),
            "wordfreq_available": bool(zipf_frequency),
        },
        "phrases": phrases,
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")


def fetch_wordnet_equivalents(phrase: str) -> Set[str]:
    if wn is None:
        return set()
    # For multi-word phrases, use the head token to avoid noisy synsets.
    head = phrase.split(" ")[0]
    out: Set[str] = set()
    for synset in wn.synsets(head):
        for lemma in synset.lemmas():
            value = normalize(lemma.name().replace("_", " "))
            if value and value != phrase:
                out.add(value)
    return out


def rank_candidates(canonical: str, candidates: Iterable[str], top_n: int = 20) -> List[Dict[str, float]]:
    scored: List[Tuple[float, str]] = []
    for candidate in candidates:
        if not candidate or candidate == canonical:
            continue
        score = score_phrase(candidate)
        scored.append((score, candidate))
    scored.sort(reverse=True)
    return [{"phrase": phrase, "frequency": score} for score, phrase in scored[:top_n]]


def score_phrase(phrase: str) -> float:
    if zipf_frequency is None:
        return max(1.0, 8.0 - (len(phrase.split(" ")) - 1) * 0.6)
    tokens = [token for token in phrase.split(" ") if token]
    if not tokens:
        return 0.0
    frequencies = [zipf_frequency(token, "en") for token in tokens]
    return round(sum(frequencies) / len(frequencies), 3)


def normalize(value: object) -> str:
    text = str(value).strip().lower()
    return " ".join(part for part in text.split() if part)


if __name__ == "__main__":
    main()

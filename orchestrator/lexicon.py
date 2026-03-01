from __future__ import annotations

import argparse
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import nltk
from nltk.corpus import wordnet as wn
from wordfreq import zipf_frequency


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NLTK_DATA_DIR = REPO_ROOT / "data" / "wordnet"
POS_MAP = {
    "noun": "n",
    "n": "n",
    "verb": "v",
    "v": "v",
    "adj": "a",
    "a": "a",
    "adjective": "a",
    "adv": "r",
    "r": "r",
    "adverb": "r",
}


def configure_nltk_data_dir(path: Optional[Path] = None) -> Path:
    """
    Configure NLTK to only use the repo-local WordNet directory.
    """
    data_dir = (path or DEFAULT_NLTK_DATA_DIR).resolve()
    os.environ["NLTK_DATA"] = str(data_dir)
    nltk.data.path[:] = [str(data_dir)]
    return data_dir


def frequency(word: str) -> float:
    """
    Return Zipf frequency (base-10 log scale) for a normalized token.
    Higher = more common; roughly 0..8 for English.
    """
    token = _normalize_token(word)
    if not token:
        return 0.0
    return float(zipf_frequency(token, "en"))


def phrase_frequency(phrase: str) -> float:
    """
    Return Zipf frequency for a phrase. If direct phrase lookup is weak,
    back off to average token Zipf frequency.
    """
    normalized = _normalize_text(phrase)
    if not normalized:
        return 0.0
    direct = float(zipf_frequency(normalized, "en"))
    if direct > 0:
        return direct
    tokens = [tok for tok in normalized.split(" ") if tok]
    if not tokens:
        return 0.0
    return sum(frequency(tok) for tok in tokens) / len(tokens)


def synonyms(term: str, *, pos: Optional[str] = None, max_results: int = 25) -> List[str]:
    _ensure_wordnet_available()
    normalized = _normalize_text(term)
    if not normalized:
        return []
    wn_pos = _normalize_pos(pos)
    values = _cached_synonyms(normalized, wn_pos, 1)
    return list(values[: max(1, max_results)])


def rank_synonyms_by_frequency(
    term: str,
    *,
    pos: Optional[str] = None,
    max_results: int = 25,
    max_synsets: int = 1,
) -> List[Tuple[str, float]]:
    _ensure_wordnet_available()
    normalized = _normalize_text(term)
    if not normalized:
        return []
    wn_pos = _normalize_pos(pos)
    return list(_cached_ranked_synonyms(normalized, wn_pos, max(1, max_results), max(1, max_synsets)))


@lru_cache(maxsize=4096)
def _cached_synonyms(normalized_term: str, wn_pos: Optional[str], max_synsets: int) -> Tuple[str, ...]:
    synsets = wn.synsets(normalized_term, pos=wn_pos)[:max(1, max_synsets)]
    results: List[str] = []
    seen = set()
    for synset in synsets:
        for lemma in synset.lemma_names():
            candidate = _normalize_text(lemma.replace("_", " "))
            if not candidate or candidate == normalized_term:
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            results.append(candidate)
    return tuple(results)


@lru_cache(maxsize=4096)
def _cached_ranked_synonyms(
    normalized_term: str,
    wn_pos: Optional[str],
    max_results: int,
    max_synsets: int,
) -> Tuple[Tuple[str, float], ...]:
    ranked = [
        (syn, phrase_frequency(syn))
        for syn in _cached_synonyms(normalized_term, wn_pos, max_synsets)[: max_results * 4]
    ]
    ranked.sort(key=lambda pair: pair[1], reverse=True)
    return tuple(ranked[: max(1, max_results)])


def _ensure_wordnet_available() -> None:
    configure_nltk_data_dir()
    missing = []
    for package in ("wordnet", "omw-1.4"):
        if not _nltk_package_available(package):
            missing.append(package)
    if missing:
        missing_text = ", ".join(missing)
        raise RuntimeError(
            f"Missing WordNet data ({missing_text}) in {DEFAULT_NLTK_DATA_DIR}. "
            "Run: python scripts/setup_wordnet.py"
        )


def _nltk_package_available(package: str) -> bool:
    for lookup_key in (f"corpora/{package}", f"corpora/{package}.zip"):
        try:
            nltk.data.find(lookup_key)
            return True
        except LookupError:
            continue
    return False


def _normalize_pos(pos: Optional[str]) -> Optional[str]:
    if pos is None:
        return None
    key = str(pos).strip().lower()
    if not key:
        return None
    if key not in POS_MAP:
        raise ValueError(f"Unsupported pos '{pos}'. Use noun/verb/adj/adv.")
    return POS_MAP[key]


def _normalize_token(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^[^\w']+|[^\w']+$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _normalize_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = " ".join(_normalize_token(part) for part in text.split(" "))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _format_ranked(rows: Iterable[Tuple[str, float]]) -> str:
    lines = []
    for term, score in rows:
        lines.append(f"  - {term}: {score:.3f}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Lookup frequency and WordNet synonyms ranked by wordfreq.")
    parser.add_argument("term", help="Word or phrase to inspect.")
    parser.add_argument("--pos", default=None, help="Optional POS: noun|verb|adj|adv")
    parser.add_argument("--top", type=int, default=20, help="Top N synonyms (default: 20)")
    args = parser.parse_args()

    configure_nltk_data_dir()
    base_freq = phrase_frequency(args.term)
    ranked = rank_synonyms_by_frequency(args.term, pos=args.pos, max_results=args.top)

    print(f"term: {args.term}")
    print(f"zipf_frequency: {base_freq:.3f}")
    print("synonyms_ranked:")
    print(_format_ranked(ranked) if ranked else "  (none)")


if __name__ == "__main__":
    main()

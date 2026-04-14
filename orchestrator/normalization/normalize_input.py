from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from orchestrator.lexicon import rank_synonyms_by_frequency
from orchestrator.normalization.lexicon import (
    Concept,
    Lexicon,
    LexiconRecord,
    normalize_surface,
    split_surface_tokens,
    tokenize_with_spans,
)
from orchestrator.normalization.synonym_store import SynonymEntry, SynonymStore


@dataclass(frozen=True)
class NormalizationResult:
    original_text: str
    normalized_text: str
    normalized_intent: Dict[str, object]
    matches: List[Dict[str, object]]
    ambiguities: List[Dict[str, object]]
    candidate_synonyms: List[Dict[str, object]]

    def as_dict(self) -> Dict[str, object]:
        return {
            "original_text": self.original_text,
            "normalized_text": self.normalized_text,
            "normalized_intent": self.normalized_intent,
            "matches": self.matches,
            "ambiguities": self.ambiguities,
            "candidate_synonyms": self.candidate_synonyms,
        }


@dataclass(frozen=True)
class NormalizationPolicy:
    min_concept_signal: float = 0.12
    min_total_margin: float = 0.35

    def is_noisy_span(self, phrase: str) -> bool:
        tokens = [tok for tok in normalize_surface(phrase).split(" ") if tok]
        if not tokens:
            return True
        # Avoid mapping broad spans like "i approach and"
        if len(tokens) > 1 and (tokens[0] in EDGE_NOISE_TOKENS or tokens[-1] in EDGE_NOISE_TOKENS):
            return True
        if len(tokens) >= 3 and sum(1 for tok in tokens if tok in EDGE_NOISE_TOKENS) >= 2:
            return True
        return False

    def allow_synonym_action_match(
        self,
        *,
        concept_id: str,
        phrase: str,
        generated: Sequence[str],
        concept_signal: float,
        best_score: float,
        second_score: float,
    ) -> bool:
        if concept_signal < self.min_concept_signal:
            return False
        if second_score > 0 and (best_score - second_score) < self.min_total_margin:
            return False

        family = ACTION_FAMILY_BY_ID.get(concept_id, "generic")
        phrase_tokens = set(tok for tok in normalize_surface(phrase).split(" ") if tok)
        top_terms = " ".join(generated[:20])

        if family == "combat":
            if not (phrase_tokens & COMBAT_CUES) and not any(cue in top_terms for cue in COMBAT_CUES):
                return False

        if family == "movement":
            # If combat-like cues dominate a span, avoid forcing movement.
            if (phrase_tokens & COMBAT_CUES) and not (phrase_tokens & MOVEMENT_CUES):
                return False

        return True


class InputNormalizer:
    def __init__(
        self,
        lexicon: Lexicon,
        *,
        synonym_store: Optional[SynonymStore] = None,
        synonym_top_n: int = 20,
        max_phrase_tokens: int = 5,
    ) -> None:
        self.lexicon = lexicon
        self.synonym_store = synonym_store or SynonymStore.from_json_path()
        self.synonym_top_n = max(5, synonym_top_n)
        self.max_phrase_tokens = max(2, max_phrase_tokens)
        self.policy = NormalizationPolicy()

        self._alias_index: Dict[Tuple[str, ...], List[str]] = {}
        self._max_alias_len = 1
        self._concept_synonyms: Dict[str, List[SynonymEntry]] = {}
        self._synonym_lookup: Dict[str, List[str]] = {}
        self._player_synonym_cache: Dict[str, List[str]] = {}

        self._build_alias_index()
        self._build_concept_synonym_index()

    @classmethod
    def for_world_model(
        cls,
        world: "WorldModel",
        *,
        lexicon_path: Optional[Path] = None,
        synonym_path: Optional[Path] = None,
        synonym_top_n: int = 20,
        max_phrase_tokens: int = 5,
    ) -> "InputNormalizer":
        from orchestrator.normalization.lexicon import Lexicon
        lexicon = Lexicon.from_world_model(world, lexicon_path=lexicon_path)
        synonym_store = SynonymStore.from_json_path(synonym_path)
        return cls(
            lexicon,
            synonym_store=synonym_store,
            synonym_top_n=synonym_top_n,
            max_phrase_tokens=max_phrase_tokens,
        )

    @classmethod
    def from_records(
        cls,
        records: Sequence[LexiconRecord],
        *,
        synonym_store: Optional[SynonymStore] = None,
    ) -> "InputNormalizer":
        return cls(Lexicon.from_records(records), synonym_store=synonym_store)

    def normalize(self, player_text: str, *, context: Optional[Mapping[str, object]] = None) -> Dict[str, object]:
        context = context or {}
        tokens = tokenize_with_spans(player_text)

        raw_matches = self._match_alias_spans(tokens)
        matches, ambiguities = self._resolve_alias_matches(raw_matches, player_text, context)

        occupied = _occupied_token_ranges(tokens, matches)

        has_action = any(match["concept_type"] == "action" for match in matches)
        if not has_action:
            rule_match = self._apply_action_rules(tokens, player_text, occupied)
            if rule_match:
                matches.append(rule_match)
                occupied = _occupied_token_ranges(tokens, matches)
                has_action = True

        synonym_matches, synonym_ambiguities, candidate_synonyms = self._cross_reference_synonyms(
            tokens,
            player_text,
            occupied,
            context,
        )
        matches.extend(synonym_matches)
        ambiguities.extend(synonym_ambiguities)

        matches.sort(key=lambda item: int(item["start"]))
        normalized_text = self._compose_normalized_text(player_text, matches)
        normalized_intent = self._build_intent(matches)

        result = NormalizationResult(
            original_text=player_text,
            normalized_text=normalized_text,
            normalized_intent=normalized_intent,
            matches=[self._public_match(match) for match in matches],
            ambiguities=ambiguities,
            candidate_synonyms=candidate_synonyms,
        )
        return result.as_dict()

    def _build_alias_index(self) -> None:
        for concept in self.lexicon.concepts:
            for alias in concept.aliases:
                phrase = split_surface_tokens(alias)
                if not phrase:
                    continue
                self._alias_index.setdefault(phrase, [])
                if concept.concept_id not in self._alias_index[phrase]:
                    self._alias_index[phrase].append(concept.concept_id)
                self._max_alias_len = max(self._max_alias_len, len(phrase))
        for concept_ids in self._alias_index.values():
            concept_ids.sort()

    def _build_concept_synonym_index(self) -> None:
        for concept in self.lexicon.concepts:
            ranked: List[SynonymEntry] = []
            base_terms = [concept.canonical_text, *concept.aliases]
            for term in base_terms:
                normalized = normalize_surface(term)
                if not normalized:
                    continue
                ranked.append(SynonymEntry(phrase=normalized, frequency=100.0))
                ranked.extend(self.synonym_store.top_for_phrase(normalized, top_n=self.synonym_top_n))

            deduped = _dedupe_ranked_entries(ranked, max_items=self.synonym_top_n)
            self._concept_synonyms[concept.concept_id] = deduped
            for entry in deduped:
                key = normalize_surface(entry.phrase)
                if not key:
                    continue
                self._synonym_lookup.setdefault(key, [])
                if concept.concept_id not in self._synonym_lookup[key]:
                    self._synonym_lookup[key].append(concept.concept_id)

        for concept_ids in self._synonym_lookup.values():
            concept_ids.sort()

    def _match_alias_spans(self, tokens: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
        matches: List[Dict[str, object]] = []
        i = 0
        while i < len(tokens):
            matched = False
            max_size = min(self._max_alias_len, len(tokens) - i)
            for size in range(max_size, 0, -1):
                phrase = tuple(str(tokens[i + j]["token"]) for j in range(size))
                concept_ids = self._alias_index.get(phrase)
                if not concept_ids:
                    continue
                start = int(tokens[i]["start"])
                end = int(tokens[i + size - 1]["end"])
                raw_text = " ".join(str(t["raw"]) for t in tokens[i : i + size])
                matches.append(
                    {
                        "start": start,
                        "end": end,
                        "token_start": i,
                        "token_end": i + size,
                        "raw_text": raw_text,
                        "concept_ids": list(concept_ids),
                        "source": "alias",
                    }
                )
                i += size
                matched = True
                break
            if not matched:
                i += 1
        return matches

    def _resolve_alias_matches(
        self,
        raw_matches: Sequence[Mapping[str, object]],
        text: str,
        context: Mapping[str, object],
    ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
        matches: List[Dict[str, object]] = []
        ambiguities: List[Dict[str, object]] = []

        for raw in raw_matches:
            concept_ids = list(raw.get("concept_ids", []))
            if not concept_ids:
                continue
            if len(concept_ids) == 1:
                concept = self.lexicon.by_id[concept_ids[0]]
                matches.append(
                    {
                        "start": int(raw["start"]),
                        "end": int(raw["end"]),
                        "raw_text": text[int(raw["start"]) : int(raw["end"])],
                        "normalized_text": concept.canonical_text,
                        "concept_id": concept.concept_id,
                        "concept_type": concept.concept_type,
                        "confidence": 0.99,
                        "source": "alias",
                    }
                )
                continue

            alias_scores = {concept_id: 1.0 for concept_id in concept_ids}
            best, tied, _best_score, _second_score = self._pick_best_concept(alias_scores, context)
            if best and not tied:
                concept = self.lexicon.by_id[best]
                matches.append(
                    {
                        "start": int(raw["start"]),
                        "end": int(raw["end"]),
                        "raw_text": text[int(raw["start"]) : int(raw["end"])],
                        "normalized_text": concept.canonical_text,
                        "concept_id": concept.concept_id,
                        "concept_type": concept.concept_type,
                        "confidence": 0.9,
                        "source": "alias_context",
                    }
                )
            else:
                ambiguities.append(self._build_ambiguity(text, raw, concept_ids, reason="ambiguous_alias"))

        return matches, ambiguities

    def _cross_reference_synonyms(
        self,
        tokens: Sequence[Mapping[str, object]],
        text: str,
        occupied: List[bool],
        context: Mapping[str, object],
    ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], List[Dict[str, object]]]:
        matches: List[Dict[str, object]] = []
        ambiguities: List[Dict[str, object]] = []
        candidate_synonyms: List[Dict[str, object]] = []

        i = 0
        while i < len(tokens):
            if occupied[i]:
                i += 1
                continue

            best_span = None
            best_concept_scores: Dict[str, float] = {}
            best_candidates: List[str] = []

            max_size = min(self.max_phrase_tokens, len(tokens) - i)
            for size in range(max_size, 1 - 1, -1):
                if any(occupied[i + k] for k in range(size)):
                    continue
                start = int(tokens[i]["start"])
                end = int(tokens[i + size - 1]["end"])
                phrase = normalize_surface(" ".join(str(tokens[i + k]["raw"]) for k in range(size)))
                if not phrase:
                    continue
                if self.policy.is_noisy_span(phrase):
                    continue
                generated = self._generate_player_synonyms(phrase, top_n=self.synonym_top_n)
                concept_scores = self._cross_reference_candidates(generated)
                if concept_scores:
                    best_span = (i, i + size, start, end, phrase)
                    best_concept_scores = concept_scores
                    best_candidates = generated
                    break

            if not best_span:
                i += 1
                continue

            token_start, token_end, start, end, phrase = best_span
            candidate_synonyms.append(
                {
                    "span": {"start": start, "end": end, "text": text[start:end]},
                    "generated": best_candidates[: self.synonym_top_n],
                }
            )

            best, tied, best_score, second_score = self._pick_best_concept(best_concept_scores, context)
            if best and not tied:
                concept = self.lexicon.by_id[best]
                concept_signal = float(best_concept_scores.get(best, 0.0))
                if concept.concept_type == "action":
                    if not self.policy.allow_synonym_action_match(
                        concept_id=concept.concept_id,
                        phrase=phrase,
                        generated=best_candidates,
                        concept_signal=concept_signal,
                        best_score=best_score,
                        second_score=second_score,
                    ):
                        i = token_end
                        continue
                matches.append(
                    {
                        "start": start,
                        "end": end,
                        "raw_text": text[start:end],
                        "normalized_text": concept.canonical_text,
                        "concept_id": concept.concept_id,
                        "concept_type": concept.concept_type,
                        "confidence": min(0.92, 0.55 + concept_signal * 0.37),
                        "source": "synonym_crossref",
                    }
                )
                for idx in range(token_start, token_end):
                    occupied[idx] = True
            else:
                raw = {"start": start, "end": end}
                ambiguities.append(
                    self._build_ambiguity(
                        text,
                        raw,
                        list(best_concept_scores.keys()),
                        reason="ambiguous_synonym_crossref",
                    )
                )
                for idx in range(token_start, token_end):
                    occupied[idx] = True
            i = token_end

        return matches, ambiguities, candidate_synonyms

    def _cross_reference_candidates(self, generated: Sequence[str]) -> Dict[str, float]:
        concept_scores: Dict[str, float] = {}
        for idx, term in enumerate(generated):
            key = normalize_surface(term)
            if not key:
                continue
            concept_ids = self._synonym_lookup.get(key, [])
            rank_signal = 1.0 / (1.0 + (idx * 0.12))
            for concept_id in concept_ids:
                existing = concept_scores.get(concept_id, 0.0)
                if rank_signal > existing:
                    concept_scores[concept_id] = rank_signal
        return concept_scores

    def _generate_player_synonyms(self, phrase: str, *, top_n: int) -> List[str]:
        cached = self._player_synonym_cache.get(phrase)
        if cached is not None:
            return cached[:top_n]

        generated = [normalize_surface(phrase)]
        generated.extend(entry.phrase for entry in self.synonym_store.top_for_phrase(phrase, top_n=top_n))
        try:
            generated.extend(
                term for term, _score in rank_synonyms_by_frequency(phrase, max_results=top_n, max_synsets=1)
            )
        except RuntimeError:
            pass
        # Also include individual-token expansions for short multiword expressions.
        tokens = [tok for tok in normalize_surface(phrase).split(" ") if tok and tok not in STOPWORDS]
        for token in tokens:
            generated.extend(entry.phrase for entry in self.synonym_store.top_for_phrase(token, top_n=top_n // 2))
            try:
                generated.extend(
                    term
                    for term, _score in rank_synonyms_by_frequency(
                        token,
                        max_results=max(3, top_n // 2),
                        max_synsets=1,
                    )
                )
            except RuntimeError:
                pass
        deduped = _dedupe_strings(generated)
        self._player_synonym_cache[phrase] = deduped
        return deduped[:top_n]

    def _apply_action_rules(
        self,
        tokens: Sequence[Mapping[str, object]],
        text: str,
        occupied: Sequence[bool],
    ) -> Optional[Dict[str, object]]:
        action_rules: List[Tuple[str, Tuple[Tuple[str, ...], ...]]] = [
            (
                "ACT_ENTER",
                (
                    ("walk", "into"),
                    ("go", "in"),
                    ("go", "inside"),
                    ("step", "inside"),
                    ("run", "into"),
                    ("head", "into"),
                    ("make", "your", "way", "to"),
                ),
            ),
            ("ACT_EXIT", (("walk", "out"), ("go", "out"), ("leave",), ("step", "out"))),
            ("ACT_TAKE", (("pick", "up"), ("grab",), ("snatch",), ("take",))),
            ("ACT_EXAMINE", (("look", "at"), ("inspect",), ("check", "out"), ("examine",))),
            ("ACT_TALK", (("talk", "to"), ("speak", "with"), ("speak", "to"), ("talk", "with"))),
        ]

        best: Optional[Dict[str, object]] = None
        for action_id, patterns in action_rules:
            concept = self.lexicon.by_id.get(action_id)
            if not concept:
                continue
            for pattern in patterns:
                match = self._find_phrase(tokens, pattern, occupied)
                if not match:
                    continue
                start_idx, end_idx = match
                candidate = {
                    "start": int(tokens[start_idx]["start"]),
                    "end": int(tokens[end_idx - 1]["end"]),
                    "raw_text": text[int(tokens[start_idx]["start"]) : int(tokens[end_idx - 1]["end"])],
                    "normalized_text": concept.canonical_text,
                    "concept_id": concept.concept_id,
                    "concept_type": concept.concept_type,
                    "confidence": 0.82,
                    "source": "rule",
                    "token_start": start_idx,
                    "token_end": end_idx,
                }
                if best is None or (end_idx - start_idx) > (best["token_end"] - best["token_start"]):
                    best = candidate
        if best:
            best.pop("token_start", None)
            best.pop("token_end", None)
        return best

    def _pick_best_concept(
        self,
        concept_scores: Mapping[str, float],
        context: Mapping[str, object],
    ) -> Tuple[Optional[str], bool, float, float]:
        scored: List[Tuple[float, str]] = []
        for concept_id, concept_signal in concept_scores.items():
            concept = self.lexicon.by_id.get(concept_id)
            if not concept:
                continue
            score = self._context_score(concept, context) + (concept_signal * 2.0)
            scored.append((score, concept_id))
        if not scored:
            return None, False, 0.0, 0.0
        scored.sort(reverse=True)
        if len(scored) == 1:
            return scored[0][1], False, scored[0][0], 0.0
        if scored[0][0] == scored[1][0]:
            return None, True, scored[0][0], scored[1][0]
        return scored[0][1], False, scored[0][0], scored[1][0]

    def _context_score(self, concept: Concept, context: Mapping[str, object]) -> float:
        score = 0.0
        visible = set(_flatten_to_lower(context.get("visible_entities") or []))
        recent = set(_flatten_to_lower(context.get("recent_entities") or []))
        current = str(context.get("current_location") or "").strip().lower()

        if concept.concept_id.lower() in visible or concept.canonical_text.lower() in visible:
            score += 3.0
        if concept.concept_id.lower() in recent or concept.canonical_text.lower() in recent:
            score += 2.0
        if current and current in {concept.concept_id.lower(), concept.canonical_text.lower()}:
            score += 4.0

        synonyms = self._concept_synonyms.get(concept.concept_id, [])
        if synonyms:
            score += min(1.0, synonyms[0].frequency / 100.0)
        return score

    def _compose_normalized_text(self, original: str, matches: Sequence[Mapping[str, object]]) -> str:
        replacing = [match for match in matches if float(match.get("confidence", 0.0)) > 0 and match.get("normalized_text")]
        replacing = sorted(replacing, key=lambda item: int(item["start"]))
        out: List[str] = []
        cursor = 0
        for match in replacing:
            start = int(match["start"])
            end = int(match["end"])
            if start < cursor:
                continue
            out.append(original[cursor:start])
            out.append(str(match["normalized_text"]))
            cursor = end
        out.append(original[cursor:])
        return "".join(out)

    def _build_intent(self, matches: Sequence[Mapping[str, object]]) -> Dict[str, object]:
        action = None
        ability_ids: List[str] = []
        targets: List[str] = []
        for match in sorted(matches, key=lambda item: (-float(item.get("confidence", 0.0)), int(item["start"]))):
            concept_type = str(match.get("concept_type") or "")
            concept_id = str(match.get("concept_id") or "")
            if concept_type == "action" and action is None:
                action = concept_id
                continue
            if concept_type == "ability" and concept_id and concept_id not in ability_ids:
                ability_ids.append(concept_id)
                continue
            if concept_type in {"location", "item", "npc", "entity"} and concept_id:
                if concept_id not in targets:
                    targets.append(concept_id)
        return {
            "action_id": action,
            "ability_ids": ability_ids,
            "target_ids": targets,
        }

    def _build_ambiguity(
        self,
        text: str,
        raw: Mapping[str, object],
        concept_ids: Sequence[str],
        *,
        reason: str,
    ) -> Dict[str, object]:
        return {
            "span": {
                "start": int(raw["start"]),
                "end": int(raw["end"]),
                "text": text[int(raw["start"]) : int(raw["end"])],
            },
            "candidates": [
                {
                    "concept_id": concept_id,
                    "concept_type": self.lexicon.by_id[concept_id].concept_type,
                    "canonical_text": self.lexicon.by_id[concept_id].canonical_text,
                }
                for concept_id in sorted(concept_ids)
                if concept_id in self.lexicon.by_id
            ],
            "reason": reason,
        }

    @staticmethod
    def _find_phrase(
        tokens: Sequence[Mapping[str, object]],
        pattern: Sequence[str],
        occupied: Sequence[bool],
    ) -> Optional[Tuple[int, int]]:
        pattern = tuple(tok.lower() for tok in pattern)
        for i in range(0, len(tokens) - len(pattern) + 1):
            if any(occupied[i + j] for j in range(len(pattern))):
                continue
            window = tuple(str(tokens[i + j]["token"]).lower() for j in range(len(pattern)))
            if window == pattern:
                return (i, i + len(pattern))
        return None

    @staticmethod
    def _public_match(match: Mapping[str, object]) -> Dict[str, object]:
        return {
            "span": {
                "start": int(match["start"]),
                "end": int(match["end"]),
                "text": str(match["raw_text"]),
            },
            "normalized_text": str(match["normalized_text"]),
            "concept_id": str(match["concept_id"]),
            "concept_type": str(match["concept_type"]),
            "confidence": float(match["confidence"]),
            "source": str(match["source"]),
        }


def _occupied_token_ranges(tokens: Sequence[Mapping[str, object]], matches: Sequence[Mapping[str, object]]) -> List[bool]:
    occupied = [False] * len(tokens)
    for match in matches:
        start = int(match["start"])
        end = int(match["end"])
        for idx, token in enumerate(tokens):
            token_start = int(token["start"])
            token_end = int(token["end"])
            if token_start >= start and token_end <= end:
                occupied[idx] = True
    return occupied


def _flatten_to_lower(values: Iterable[object]) -> List[str]:
    lowered: List[str] = []
    for value in values:
        cleaned = str(value).strip().lower()
        if cleaned:
            lowered.append(cleaned)
    return lowered


def _dedupe_strings(values: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        cleaned = normalize_surface(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _dedupe_ranked_entries(values: Iterable[SynonymEntry], *, max_items: int) -> List[SynonymEntry]:
    best_by_phrase: Dict[str, float] = {}
    for entry in values:
        key = normalize_surface(entry.phrase)
        if not key:
            continue
        current = best_by_phrase.get(key)
        if current is None or entry.frequency > current:
            best_by_phrase[key] = entry.frequency
    ordered = sorted(
        (SynonymEntry(phrase=phrase, frequency=freq) for phrase, freq in best_by_phrase.items()),
        key=lambda item: item.frequency,
        reverse=True,
    )
    return ordered[:max_items]


STOPWORDS = {
    "about",
    "a",
    "an",
    "and",
    "as",
    "at",
    "for",
    "from",
    "i",
    "in",
    "into",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "you",
}

EDGE_NOISE_TOKENS = {
    "a",
    "an",
    "and",
    "but",
    "i",
    "then",
    "the",
}

ACTION_FAMILY_BY_ID = {
    "ACT_MOVE": "movement",
    "ACT_ENTER": "movement",
    "ACT_EXIT": "movement",
    "ACT_TALK": "social",
    "ACT_EXAMINE": "knowledge",
    "ACT_TAKE": "object",
    "ACT_ATTACK": "combat",
    "ACT_CAST": "combat",
    "ACT_HIDE": "movement",
    "ACT_JUMP": "movement",
}

COMBAT_CUES = {
    "attack",
    "fight",
    "hit",
    "kill",
    "punch",
    "slash",
    "smash",
    "stab",
    "strike",
    "swing",
}

MOVEMENT_CUES = {
    "approach",
    "enter",
    "go",
    "head",
    "move",
    "travel",
    "walk",
}

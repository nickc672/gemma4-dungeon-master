# dungeon-masters-companion
The Dungeon Masters Companion is a proposed structure for creating a MCP-powered AI DM system for TTRPGs.

## Quickstart
- Default demo (built-in tavern nodes): `python -m orchestrator.cli`
- Add `--verbose` to see planner/validator prompts, and `--starting-state` if you want to override the default opening.

## Offline Frequency + Synonyms (wordfreq + WordNet)
This repo now includes `orchestrator/lexicon.py`, an offline-capable API for English frequency and synonyms.

Install dependencies:
- `python -m pip install -r requirements.txt`

Download WordNet corpora into repo-local storage (`./data/wordnet`):
- `python scripts/setup_wordnet.py`

API usage:
```python
from orchestrator.lexicon import frequency, phrase_frequency, synonyms, rank_synonyms_by_frequency

print(frequency("the"))                     # Zipf scale float
print(phrase_frequency("walk into"))        # phrase Zipf (fallback to token average)
print(synonyms("car", pos="noun", max_results=20))
print(rank_synonyms_by_frequency("enter", pos="verb", max_results=20))
```

CLI usage:
- `python -m orchestrator.lexicon "term here" --pos noun --top 20`
- `python -m orchestrator.lexicon "walk into" --pos verb --top 20`

Normalization speed benchmark:
- `python scripts/benchmark_normalization.py --top-values 20,40,80,120,160,200 --rounds 80`
- Current default in `Orchestrator` is `normalization_top_n=400` (tunable).

## Player Input Normalization
An additive normalization step now runs at the start of each turn in `orchestrator/pipeline.py`.

- Module entry point: `orchestrator/normalization/normalize_input.py`
- Lexicon loader: `orchestrator/normalization/lexicon.py`
- Canonical game lexicon: `orchestrator/data/normalization_lexicon.json`
- Ranked synonym dictionary store: `orchestrator/data/synonym_store.json`

How it works:
- Canonical lexicon is built from story nodes (persons/places/things) plus configured actions/abilities.
- Direct canonical/alias matching runs first with longest-match-first span resolution.
- Rule-based gameplay paraphrases run next (only when no high-confidence action alias was matched).
- For remaining spans, player phrase candidates are expanded into a ranked top-N synonym list from hard storage and cross-referenced against top-N synonym lists for canonical concepts.
- Ambiguous mappings are surfaced in `ambiguities` and are not blindly replaced.

Turn output now includes a `normalization` block with:
- `normalized_text`
- `normalized_intent` (`action_id`, `ability_ids`, `target_ids`)
- `matches` (spans, confidence, source)
- `ambiguities` (candidate concepts)
- `candidate_synonyms` (player-generated top synonym candidates per processed span)

### Adding Aliases
Update `orchestrator/data/normalization_lexicon.json`:

- Add action aliases under `actions` with `concept_id`, `canonical_text`, and `aliases`.
- Add DnD-style ability concepts under `abilities`.
- Add entity aliases under `entities` with `canonical_text`, `concept_type`, and `aliases`.
- Existing story aliases in `StoryGraph._ALIASES` are also ingested automatically.

### Building A New Synonym Store
You can regenerate a ranked store from WordNet/frequency data and write it to disk:

- `python tools/build_synonym_store.py`

If installed, the script uses:
- `nltk` WordNet for synonym candidates
- `wordfreq` for frequency-based ranking

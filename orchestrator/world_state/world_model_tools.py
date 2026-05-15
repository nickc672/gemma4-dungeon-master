from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .entity import Entity
from .item import Item
from .location import Location
from .story import GameState
from .tool_runtime import (
    get_runtime_alias_registry,
    get_runtime_world_model,
    normalize_key,
    register_entity_aliases,
    require_turn_orchestration_ctx,
    resolve_alias,
    save_runtime_world_checkpoint,
)
import re
from .world_model import WORLD_MODEL_DATA_DIR, WorldModel, build_world_model


# Per-turn caps to prevent runaway creation.
MAX_ENTITY_CREATIONS_PER_TURN = 2
MAX_ITEM_CREATIONS_PER_TURN = 3

# Reserved entity keys that must never be overwritten at runtime.
_PROTECTED_KEYS = {"player"}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _first_location_key(model: WorldModel) -> str:
    if not model.locations:
        return ""
    return sorted(model.locations.values(), key=lambda value: value.key.lower())[0].key


def _resolve_location_candidate(model: WorldModel, location_key: str) -> str:
    candidate = str(location_key or "").strip()
    if not candidate:
        return ""
    location = model.get_location(candidate)
    if location is not None:
        return location.key

    needle = _normalize_text(candidate)
    for location_value in model.locations.values():
        if needle in _normalize_text(location_value.key) or needle in _normalize_text(location_value.name):
            return location_value.key
    return ""


# Stopwords we strip when computing token overlap for fuzzy matches.
_STOPWORDS = {
    "a", "an", "the", "of", "to", "in", "on", "at", "by", "for", "with",
    "and", "or", "but", "is", "was", "are", "were", "be", "been", "being",
    "this", "that", "these", "those", "it", "its", "as", "from", "near",
    "here", "there", "someone", "person", "thing", "object", "man", "woman",
    "boy", "girl", "guy", "lady", "stranger", "figure",
}

# Article prefixes that the LLM commonly attaches to descriptor phrases.
_ARTICLE_PREFIXES = ("the ", "a ", "an ", "some ", "this ", "that ")


def _strip_articles(text: str) -> str:
    """Strip a leading article from a descriptor phrase so substring matches are looser."""
    cleaned = _normalize_text(text)
    for prefix in _ARTICLE_PREFIXES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    return cleaned


def _content_tokens(text: str) -> set[str]:
    """Tokenize a string into lowercase content words (alphanumeric, length >= 3, non-stopword)."""
    words = re.findall(r"[a-z0-9']+", _normalize_text(text))
    return {word for word in words if len(word) >= 3 and word not in _STOPWORDS}


def _resolve_candidate_via_aliases(game_state: GameState | None, candidate: str) -> str:
    """
    Look up the alias registry for a canonical key matching candidate.

    Tries, in order:
      1. Direct registry lookup against the raw candidate.
      2. Direct registry lookup against the article-stripped candidate.
      3. Scan of all registered aliases: if any registered alias matches
         either the candidate or the candidate's stripped form when the
         registered alias is itself stripped of leading articles, return it.

    Step 3 handles the common case where the registry contains
    "a man with a scar" and the player input says "the man with a scar"
    (or vice versa).
    """
    if game_state is None or not candidate:
        return ""
    direct = resolve_alias(game_state, candidate)
    if direct:
        return direct

    stripped_candidate = _strip_articles(candidate)
    if stripped_candidate and stripped_candidate != _normalize_text(candidate):
        hit = resolve_alias(game_state, stripped_candidate)
        if hit:
            return hit

    registry = get_runtime_alias_registry(game_state)
    if not registry:
        return ""

    target_forms = {_normalize_text(candidate)}
    if stripped_candidate:
        target_forms.add(stripped_candidate)

    for alias_key, canonical in registry.items():
        stripped_alias = _strip_articles(alias_key)
        if stripped_alias and stripped_alias in target_forms:
            return canonical
    return ""


def _resolve_entity_candidate(
    model: WorldModel,
    entity_key: str,
    game_state: GameState | None = None,
    *,
    exclude_protected: bool = True,
) -> str:
    """
    Resolve a free-form entity reference to a canonical key.

    Resolution order:
      1. Direct key lookup against the world model. (Protected keys are
         still returned here if the caller asks for them explicitly.)
      2. Alias registry lookup (both raw and article-stripped form).
      3. Substring match against existing entity keys, names, and
         descriptions. Protected entities (e.g. Player) are skipped when
         exclude_protected is True.
      4. Content-token overlap against names and descriptions. The overlap
         must be at least the larger of 3 tokens or a majority of the
         candidate's content tokens. Memory sentences are intentionally not
         scanned here: memory accumulates location names and event vocabulary
         that bleed across unrelated entities and produce false positives.
         Protected entities are skipped when exclude_protected is True.

    exclude_protected defaults to True because the resolver is most often
    called from create_npc / dedup paths where matching the Player entity
    is always wrong.
    """
    candidate = str(entity_key or "").strip()
    if not candidate:
        return ""

    entity = model.get_entity(candidate)
    if entity is not None:
        return entity.key

    alias_hit = _resolve_candidate_via_aliases(game_state, candidate)
    if alias_hit:
        existing = model.get_entity(alias_hit)
        if existing is not None:
            if not (exclude_protected and _normalize_text(existing.key) in _PROTECTED_KEYS):
                return existing.key
            # Aliases must never silently resolve to Player from a
            # materialisation path; fall through to the remaining checks.

    needle = _normalize_text(candidate)
    stripped_needle = _strip_articles(candidate)
    for entity_value in model.entities.values():
        if exclude_protected and _normalize_text(entity_value.key) in _PROTECTED_KEYS:
            continue
        haystack_key = _normalize_text(entity_value.key)
        haystack_name = _normalize_text(entity_value.name)
        haystack_desc = _normalize_text(entity_value.description)
        if needle and (needle in haystack_key or needle in haystack_name or needle in haystack_desc):
            return entity_value.key
        if stripped_needle and stripped_needle != needle:
            if (
                stripped_needle in haystack_key
                or stripped_needle in haystack_name
                or stripped_needle in haystack_desc
            ):
                return entity_value.key

    # Token-overlap fallback. Restricted to name + description so that
    # accumulated memory does not produce false positives between unrelated
    # entities that happen to share location vocabulary (e.g. Player's
    # memory of "I walked to Town Hall" matching a candidate "The Town Hall
    # Clerk").
    candidate_tokens = _content_tokens(candidate)
    min_required = max(3, (len(candidate_tokens) + 1) // 2)
    if len(candidate_tokens) >= 3:
        best_key = ""
        best_score = 0
        for entity_value in model.entities.values():
            if exclude_protected and _normalize_text(entity_value.key) in _PROTECTED_KEYS:
                continue
            entity_tokens = _content_tokens(entity_value.name)
            entity_tokens |= _content_tokens(entity_value.description)
            overlap = len(candidate_tokens & entity_tokens)
            if overlap >= min_required and overlap > best_score:
                best_score = overlap
                best_key = entity_value.key
        if best_key:
            return best_key

    return ""


def _resolve_item_candidate(
    model: WorldModel,
    item_key: str,
    game_state: GameState | None = None,
) -> str:
    """Resolve a free-form item reference. Same strategy as _resolve_entity_candidate."""
    candidate = str(item_key or "").strip()
    if not candidate:
        return ""

    item = model.get_item(candidate)
    if item is not None:
        return item.key

    alias_hit = _resolve_candidate_via_aliases(game_state, candidate)
    if alias_hit:
        existing = model.get_item(alias_hit)
        if existing is not None:
            return existing.key

    needle = _normalize_text(candidate)
    stripped_needle = _strip_articles(candidate)
    for item_value in model.items.values():
        haystack_key = _normalize_text(item_value.key)
        haystack_name = _normalize_text(item_value.name)
        haystack_desc = _normalize_text(item_value.description)
        if needle and (needle in haystack_key or needle in haystack_name or needle in haystack_desc):
            return item_value.key
        if stripped_needle and stripped_needle != needle:
            if (
                stripped_needle in haystack_key
                or stripped_needle in haystack_name
                or stripped_needle in haystack_desc
            ):
                return item_value.key

    # Token-overlap fallback. Restricted to name + description (see entity
    # resolver for rationale).
    candidate_tokens = _content_tokens(candidate)
    min_required = max(3, (len(candidate_tokens) + 1) // 2)
    if len(candidate_tokens) >= 3:
        best_key = ""
        best_score = 0
        for item_value in model.items.values():
            item_tokens = _content_tokens(item_value.name)
            item_tokens |= _content_tokens(item_value.description)
            overlap = len(candidate_tokens & item_tokens)
            if overlap >= min_required and overlap > best_score:
                best_score = overlap
                best_key = item_value.key
        if best_key:
            return best_key

    return ""


# ---------------------------------------------------------------------------
# Location memory linking
# ---------------------------------------------------------------------------

_LINK_MARKER_TEMPLATE = "now known as {name}, key: {key}"


def _has_existing_link_for_key(sentence: str, canonical_key: str) -> bool:
    """Return True if the sentence already carries a back-reference for canonical_key."""
    if not sentence or not canonical_key:
        return False
    marker = f"key: {canonical_key}".lower()
    return marker in sentence.lower()


def _candidate_link_phrases(canonical_name: str, aliases: list[str] | None) -> list[str]:
    """
    Build the ordered list of surface forms we will try to back-reference in
    location memory sentences. Longer phrases are tried first so we replace
    the most specific match rather than a bare noun.
    """
    seen: set[str] = set()
    phrases: list[str] = []

    candidates: list[str] = []
    if canonical_name:
        candidates.append(canonical_name)
    for alias in aliases or []:
        text = str(alias or "").strip()
        if text:
            candidates.append(text)

    for phrase in candidates:
        cleaned = phrase.strip()
        if not cleaned:
            continue
        token_count = len(cleaned.split())
        if token_count < 1:
            continue
        # A single bare token like "man" is too noisy; require at least two
        # tokens unless the phrase is the entity's display name itself.
        if token_count == 1 and cleaned.lower() != canonical_name.strip().lower():
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        phrases.append(cleaned)

    # Longer phrases first so we match the most specific descriptor in a sentence.
    phrases.sort(key=lambda value: (-len(value.split()), -len(value)))
    return phrases


def _replace_phrase_once(sentence: str, phrase: str, marker: str) -> tuple[str, bool]:
    """
    Append a parenthesised marker after the first case-insensitive occurrence
    of phrase in sentence. The matched text itself is preserved verbatim so
    the original surface form ("a man with a scar" vs "A Man With A Scar")
    is not overwritten by the display-name capitalisation.

    Returns (new_sentence, matched).
    """
    if not phrase:
        return sentence, False
    pattern = re.compile(re.escape(phrase), re.IGNORECASE)

    def _replacement(match: re.Match) -> str:
        return f"{match.group(0)} ({marker})"

    new_sentence, count = pattern.subn(_replacement, sentence, count=1)
    return new_sentence, count > 0


def _link_location_memory_for_new_object(
    model: WorldModel,
    game_state: GameState,
    canonical_key: str,
    canonical_name: str,
    aliases: list[str] | None,
    description: str = "",
) -> dict[str, Any]:
    """
    Rewrite sentences in the player's current location memory that describe
    the just-materialized world object, embedding a back-reference to the
    canonical key. Append a fresh memory line announcing the materialization
    if any sentence matched. Return matched sentences (pre-rewrite) so they
    can be seeded onto the new entity for backstory continuity.

    Pure mutation on the model; the caller is responsible for saving.
    """
    result: dict[str, Any] = {
        "matched_sentences": [],
        "rewrites": 0,
        "appended_line": "",
    }

    if game_state is None or not canonical_key:
        return result

    location_key = str(getattr(game_state, "player_location", "") or "").strip()
    if not location_key:
        return result

    location = model.get_location(location_key)
    if location is None:
        return result

    phrases = _candidate_link_phrases(canonical_name, aliases)
    if not phrases:
        return result

    replacement_marker = _LINK_MARKER_TEMPLATE.format(
        name=canonical_name.strip() or canonical_key,
        key=canonical_key,
    )

    sentences = location.memory.sentences
    matched_sentences: list[str] = []
    best_match_phrase = ""

    for index, raw_sentence in enumerate(list(sentences)):
        sentence = str(raw_sentence)
        if not sentence.strip():
            continue
        if _has_existing_link_for_key(sentence, canonical_key):
            # Already linked on a prior turn; do not double-annotate.
            continue

        rewritten = sentence
        matched_this_sentence = False
        matched_phrase_here = ""

        for phrase in phrases:
            new_text, changed = _replace_phrase_once(rewritten, phrase, replacement_marker)
            if changed:
                rewritten = new_text
                matched_this_sentence = True
                matched_phrase_here = phrase
                # Stop trying further phrases against this sentence. The
                # marker we just inserted contains the canonical name itself,
                # so continuing would match that name inside the marker and
                # produce nested wrappings.
                break

        if matched_this_sentence:
            matched_sentences.append(sentence)
            sentences[index] = rewritten
            result["rewrites"] += 1
            if not best_match_phrase:
                best_match_phrase = matched_phrase_here

    if matched_sentences:
        descriptor = best_match_phrase or phrases[0]
        # The announcement carries the same "key: <canonical_key>" marker so
        # subsequent linker passes recognize it as already linked and do not
        # try to wrap the entity's display name again.
        announcement = (
            f"The player engaged with what was previously described as "
            f"\"{descriptor}\". This is {replacement_marker}."
        )
        if announcement not in sentences:
            sentences.append(announcement)
            result["appended_line"] = announcement

    result["matched_sentences"] = matched_sentences
    _ = description  # reserved for future heuristics; intentionally unused.
    return result


def _default_scene_location(model: WorldModel, game_state: GameState | None) -> str:
    if game_state is not None and str(game_state.player_location or "").strip():
        resolved = _resolve_location_candidate(model, game_state.player_location)
        if resolved:
            return resolved
    if model.starting_location:
        resolved = _resolve_location_candidate(model, model.starting_location)
        if resolved:
            return resolved
    return _first_location_key(model)


def _default_scene_entity(model: WorldModel, game_state: GameState | None) -> str:
    player = model.get_entity("Player")
    if player is not None:
        return player.key
    location_key = _default_scene_location(model, game_state)
    if location_key:
        actors = model.scene_snapshot(location_key).get("actors_here", [])
        for actor_key in actors:
            resolved = _resolve_entity_candidate(model, str(actor_key))
            if resolved:
                return resolved
    if model.entities:
        return sorted(model.entities.values(), key=lambda value: value.key.lower())[0].key
    return ""


def _default_scene_item(model: WorldModel, game_state: GameState | None) -> str:
    location_key = _default_scene_location(model, game_state)
    if location_key:
        scene_items = model.scene_snapshot(location_key).get("items_here", [])
        for item_key in scene_items:
            resolved = _resolve_item_candidate(model, str(item_key))
            if resolved:
                return resolved
    if model.items:
        return sorted(model.items.values(), key=lambda value: value.key.lower())[0].key
    return ""


def _resolve_data_dir(world_model_data_dir: str = "") -> Path:
    if str(world_model_data_dir or "").strip():
        return Path(str(world_model_data_dir)).expanduser().resolve()
    return WORLD_MODEL_DATA_DIR


def _load_model(world_model_data_dir: str = "", game_state: GameState | None = None) -> WorldModel:
    if game_state is not None:
        return get_runtime_world_model(game_state)
    return build_world_model(data_dir=_resolve_data_dir(world_model_data_dir))


def _save_model(
    model: WorldModel,
    world_model_data_dir: str = "",
    *,
    game_state: GameState | None = None,
    checkpoint_name: str = "",
) -> str:
    if game_state is not None:
        checkpoint_dir = save_runtime_world_checkpoint(game_state, checkpoint_name=checkpoint_name)
        return str(checkpoint_dir) if checkpoint_dir is not None else ""
    save_dir = _resolve_data_dir(world_model_data_dir)
    model.save(data_dir=save_dir)
    return str(save_dir)


def _get_turn_creation_counts(game_state: GameState) -> dict[str, int]:
    """Return the creation-count dict stored in the active turn context."""
    try:
        ctx = require_turn_orchestration_ctx(game_state)
        return ctx.setdefault("creation_counts", {"entities": 0, "items": 0})
    except Exception:
        return {"entities": 0, "items": 0}


def _slug(text: str) -> str:
    """Convert a display name to a safe key slug."""
    return _normalize_text(text).replace(" ", "_").replace("-", "_")


def _unique_key(model: WorldModel, base: str) -> str:
    """Return base if unused in the model, otherwise append an incrementing suffix."""
    if not model.has_key(base):
        return base
    suffix = 2
    while True:
        candidate = f"{base}_{suffix}"
        if not model.has_key(candidate):
            return candidate
        suffix += 1


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------

def get_world_story(world_model_data_dir: str = "", game_state: GameState | None = None) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    return {"success": True, "story": model.story_record()}


def write_world_story(
    starting_location: str | None = None,
    starting_state: str | None = None,
    beat_list: list[str] | None = None,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    model.set_story(
        starting_location=starting_location,
        starting_state=starting_state,
        beat_list=beat_list,
    )
    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors}
    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )
    return {"success": True, "story": model.story_record(), "save_path": save_path}


def list_world_locations(world_model_data_dir: str = "", game_state: GameState | None = None) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    return {"success": True, "locations": model.list_location_records()}


def get_world_location(
    location_key: str = "",
    world_model_data_dir: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    resolved_key = _resolve_location_candidate(model, location_key) or _default_scene_location(model, game_state)
    if not resolved_key:
        return {
            "success": True,
            "location": None,
            "reason": "No locations are available in the world model.",
        }
    location = model.get_location(resolved_key)
    if location is None:
        return {
            "success": False,
            "reason": f"Unknown location '{location_key}'.",
            "retryable": False,
        }
    return {
        "success": True,
        "location": location.to_record(),
        "resolved_location_key": resolved_key,
    }


def upsert_world_location(
    location_key: str,
    name: str = "",
    description: str = "",
    connections: list[str] | None = None,
    tags: list[str] | None = None,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    existing = model.get_location(location_key)
    location = Location(
        key=location_key,
        name=name or (existing.name if existing else location_key),
        description=description or (existing.description if existing else ""),
        connections=[str(value) for value in (connections if connections is not None else (existing.connections if existing else []))],
        tags=[str(value) for value in (tags if tags is not None else (existing.tags if existing else []))],
    )
    model.add_location(location)
    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors}
    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )
    return {"success": True, "location": location.to_record(), "save_path": save_path}


def connect_world_locations(
    location_key: str,
    other_location_key: str,
    bidirectional: bool = True,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    if not model.connect_locations(location_key, other_location_key, bidirectional=bool(bidirectional)):
        return {"success": False, "reason": "Both locations must exist before they can be connected."}
    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors}
    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )
    return {
        "success": True,
        "scene": model.scene_snapshot(location_key),
        "other_scene": model.scene_snapshot(other_location_key),
        "save_path": save_path,
    }


def get_world_scene(
    location_key: str = "",
    world_model_data_dir: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    resolved_key = _resolve_location_candidate(model, location_key) or _default_scene_location(model, game_state)
    if not resolved_key:
        return {"success": True, "scene": {"location": "", "description": "Unknown location", "connections": [], "actors_here": [], "items_here": []}}
    return {"success": True, "scene": model.scene_snapshot(resolved_key), "resolved_location_key": resolved_key}


def list_world_entities(
    entity_type: str = "",
    world_model_data_dir: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    return {"success": True, "entities": model.list_entity_records(entity_type=entity_type or None)}


def get_world_entity(
    entity_key: str = "",
    world_model_data_dir: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    resolved_key = _resolve_entity_candidate(model, entity_key, game_state=game_state) or _default_scene_entity(model, game_state)
    if not resolved_key:
        return {
            "success": True,
            "entity": None,
            "inventory": [],
            "reason": "No entities are available in the world model.",
        }
    entity = model.get_entity(resolved_key)
    if entity is None:
        return {
            "success": False,
            "reason": f"Unknown entity '{entity_key}'.",
            "retryable": False,
        }
    return {
        "success": True,
        "entity": entity.to_record(),
        "inventory": list(entity.inventory),
        "resolved_entity_key": resolved_key,
    }


def upsert_world_entity(
    entity_key: str,
    name: str = "",
    entity_type: str = "npc",
    description: str = "",
    location: str = "",
    skills: dict[str, int] | None = None,
    stats: dict[str, int] | None = None,
    tags: list[str] | None = None,
    memory: list[str] | None = None,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    existing = model.get_entity(entity_key)
    payload = {
        "key": entity_key,
        "name": name or (existing.name if existing else entity_key),
        "entity_type": entity_type or (existing.entity_type if existing else "npc"),
        "description": description or (existing.description if existing else ""),
        "location": location or (existing.location if existing else model.starting_location),
        "skills": skills if skills is not None else (dict(existing.skills) if existing else {}),
        "stats": stats if stats is not None else (dict(existing.stats) if existing else {}),
        "tags": tags if tags is not None else (list(existing.tags) if existing else []),
        "memory": memory if memory is not None else (list(existing.memory.sentences) if existing else []),
    }
    entity = Entity.from_record(payload)
    model.add_entity(entity)
    model.sync_actor_inventories()
    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors}
    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )
    return {"success": True, "entity": entity.to_record(), "save_path": save_path}


def move_world_entity(
    entity_key: str,
    location_key: str,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    if not model.move_entity(entity_key, location_key):
        return {"success": False, "reason": "Entity and location must both exist."}
    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors}
    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )
    entity = model.get_entity(entity_key)
    return {"success": True, "entity": entity.to_record() if entity else None, "save_path": save_path}


def list_world_items(
    holder_kind: str = "",
    holder_key: str = "",
    world_model_data_dir: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    return {
        "success": True,
        "items": model.list_item_records(
            holder_kind=holder_kind or None,
            holder_key=holder_key or None,
        ),
    }


def get_world_item(
    item_key: str = "",
    world_model_data_dir: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    resolved_key = _resolve_item_candidate(model, item_key, game_state=game_state) or _default_scene_item(model, game_state)
    if not resolved_key:
        return {
            "success": True,
            "item": None,
            "reason": "No items are available in the world model.",
        }
    item = model.get_item(resolved_key)
    if item is None:
        return {
            "success": False,
            "reason": f"Unknown item '{item_key}'.",
            "retryable": False,
        }
    return {
        "success": True,
        "item": item.to_record(),
        "resolved_item_key": resolved_key,
    }


def upsert_world_item(
    item_key: str,
    name: str = "",
    description: str = "",
    holder_kind: str = "",
    holder_key: str = "",
    portable: bool | None = None,
    tags: list[str] | None = None,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    existing = model.get_item(item_key)
    item = Item.from_record(
        {
            "key": item_key,
            "name": name or (existing.name if existing else item_key),
            "description": description or (existing.description if existing else ""),
            "holder_kind": holder_kind or (existing.holder_kind if existing else "location"),
            "holder_key": holder_key or (existing.holder_key if existing else model.starting_location),
            "portable": bool(portable) if portable is not None else (existing.portable if existing else True),
            "tags": tags if tags is not None else (list(existing.tags) if existing else []),
        }
    )
    model.add_item(item)
    model.sync_actor_inventories()
    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors}
    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )
    return {"success": True, "item": item.to_record(), "save_path": save_path}


def move_world_item(
    item_key: str,
    holder_kind: str,
    holder_key: str,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    normalized_kind = str(holder_kind or "").strip().lower()
    if normalized_kind == "location":
        ok = model.move_item_to_location(item_key, holder_key)
    elif normalized_kind == "entity":
        ok = model.move_item_to_entity(item_key, holder_key)
    else:
        return {"success": False, "reason": "holder_kind must be 'location' or 'entity'."}
    if not ok:
        return {"success": False, "reason": "Item and target holder must both exist."}
    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors}
    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )
    item = model.get_item(item_key)
    return {"success": True, "item": item.to_record() if item else None, "save_path": save_path}


def validate_world_model(world_model_data_dir: str = "", game_state: GameState | None = None) -> dict[str, Any]:
    model = _load_model(world_model_data_dir, game_state=game_state)
    errors = model.validate()
    return {"success": not errors, "errors": errors}


# ---------------------------------------------------------------------------
# Runtime creation tools (Phase 2 only)
# ---------------------------------------------------------------------------

def create_npc(
    name: str,
    description: str = "",
    location: str = "",
    tags: list[str] | None = None,
    aliases: list[str] | None = None,
    memory_seeds: list[str] | None = None,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    """
    Create a new NPC in the world model when the player directly interacts
    with a character that has not been registered yet.
    """
    if game_state is None:
        return {"success": False, "reason": "Missing game_state context.", "retryable": False}

    clean_name = str(name or "").strip()
    if not clean_name:
        return {"success": False, "reason": "name is required.", "retryable": False}

    # Player identity protection
    if _normalize_text(clean_name) in _PROTECTED_KEYS:
        return {
            "success": False,
            "reason": "Cannot create an entity using a reserved name.",
            "retryable": False,
        }

    model = _load_model(world_model_data_dir, game_state=game_state)

    # Find before create - search the full world via the alias registry, key /
    # name / description substring, and content-token overlap (not just the
    # current scene). exclude_protected (the resolver default) guarantees the
    # Player entity can never be returned as a "found" match for a new NPC.
    existing_key = _resolve_entity_candidate(model, clean_name, game_state=game_state)
    if not existing_key:
        # Also probe each passed alias through the resolver. The LLM may pick
        # a brand-new display name even though an alias already exists.
        for alias_candidate in (aliases or []):
            existing_key = _resolve_entity_candidate(
                model, str(alias_candidate), game_state=game_state
            )
            if existing_key:
                break

    # Defence in depth: even if some resolver call somewhere returns a
    # protected key, refuse to treat that as a duplicate match for a new
    # NPC. Materialisation must never collapse into the Player.
    if existing_key and _normalize_text(existing_key) in _PROTECTED_KEYS:
        existing_key = ""
    if existing_key:
        existing = model.get_entity(existing_key)
        # Register any new aliases on the already-existing entity so follow-up
        # references from the player also resolve.
        all_aliases = [clean_name] + (list(aliases) if aliases else [])
        register_entity_aliases(game_state, existing_key, all_aliases)

        # Even on the find branch we link the current location memory: the
        # player may be interacting at a different location than the one that
        # originally described this entity, in which case fresh descriptors
        # here should also be back-referenced.
        link_result = _link_location_memory_for_new_object(
            model,
            game_state,
            canonical_key=existing_key,
            canonical_name=existing.name if existing is not None else clean_name,
            aliases=all_aliases,
            description=description,
        )

        save_path = ""
        if link_result.get("rewrites") or link_result.get("appended_line"):
            save_path = _save_model(
                model,
                world_model_data_dir,
                game_state=game_state,
                checkpoint_name=checkpoint_name,
            )

        return {
            "success": True,
            "created": False,
            "key": existing_key,
            "entity": existing.to_record() if existing else None,
            "reason": f"Entity matching '{clean_name}' already exists as '{existing_key}'.",
            "location_memory_link": {
                "rewrites": link_result.get("rewrites", 0),
                "appended_line": link_result.get("appended_line", ""),
            },
            "save_path": save_path,
        }

    # Per-turn cap
    counts = _get_turn_creation_counts(game_state)
    if counts["entities"] >= MAX_ENTITY_CREATIONS_PER_TURN:
        return {
            "success": False,
            "reason": (
                f"Per-turn entity creation cap ({MAX_ENTITY_CREATIONS_PER_TURN}) reached. "
                "Cannot create more entities this turn."
            ),
            "retryable": False,
        }

    entity_key = _unique_key(model, _slug(clean_name))

    # Resolve location - default to the player's current location.
    resolved_location = ""
    if location:
        resolved_location = _resolve_location_candidate(model, location)
    if not resolved_location:
        resolved_location = _resolve_location_candidate(model, game_state.player_location)
    if not resolved_location:
        resolved_location = game_state.player_location
    if not resolved_location:
        resolved_location = model.starting_location

    payload: dict[str, Any] = {
        "key": entity_key,
        "name": clean_name,
        "entity_type": "npc",
        "description": str(description or "").strip(),
        "location": resolved_location,
        "skills": {},
        "stats": {},
        "tags": [str(t) for t in (tags or [])],
        "memory": [str(m) for m in (memory_seeds or [])],
    }
    entity = Entity.from_record(payload)
    model.add_entity(entity)
    model.sync_actor_inventories()

    # Link any prior location memory sentences that described this character
    # (e.g. "a man with a scar watches from the corner") to the new canonical
    # key, append an announcement line on the location, and seed the new
    # entity with the original descriptive sentences so its backstory carries
    # over.
    all_aliases = [clean_name] + (list(aliases) if aliases else [])
    link_result = _link_location_memory_for_new_object(
        model,
        game_state,
        canonical_key=entity_key,
        canonical_name=clean_name,
        aliases=all_aliases,
        description=description,
    )
    matched = list(link_result.get("matched_sentences") or [])
    if matched:
        existing_memory = set(entity.memory.sentences)
        carried_over: list[str] = []
        for sentence in matched:
            if sentence and sentence not in existing_memory:
                carried_over.append(
                    f"Origin (from location memory): {sentence}"
                )
                existing_memory.add(sentence)
        if carried_over:
            entity.memory.add_sentences(carried_over)

    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors, "retryable": False}

    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )

    counts["entities"] += 1

    register_entity_aliases(game_state, entity_key, all_aliases)

    return {
        "success": True,
        "created": True,
        "key": entity_key,
        "entity": entity.to_record(),
        "save_path": save_path,
        "location_memory_link": {
            "rewrites": link_result.get("rewrites", 0),
            "appended_line": link_result.get("appended_line", ""),
            "matched_sentence_count": len(matched),
        },
    }


def create_item(
    name: str,
    description: str = "",
    holder_kind: str = "location",
    holder_key: str = "",
    portable: bool = True,
    tags: list[str] | None = None,
    aliases: list[str] | None = None,
    world_model_data_dir: str = "",
    checkpoint_name: str = "",
    game_state: GameState | None = None,
) -> dict[str, Any]:
    """
    Create a new item in the world model when the player directly interacts
    with an object that has not been registered yet.
    """
    if game_state is None:
        return {"success": False, "reason": "Missing game_state context.", "retryable": False}

    clean_name = str(name or "").strip()
    if not clean_name:
        return {"success": False, "reason": "name is required.", "retryable": False}

    model = _load_model(world_model_data_dir, game_state=game_state)

    # Find before create - alias registry first, then key/name/description
    # substring, then content-token overlap.
    existing_key = _resolve_item_candidate(model, clean_name, game_state=game_state)
    if not existing_key:
        for alias_candidate in (aliases or []):
            existing_key = _resolve_item_candidate(model, str(alias_candidate), game_state=game_state)
            if existing_key:
                break
    if existing_key:
        existing = model.get_item(existing_key)
        all_aliases = [clean_name] + (list(aliases) if aliases else [])
        register_entity_aliases(game_state, existing_key, all_aliases)

        link_result = _link_location_memory_for_new_object(
            model,
            game_state,
            canonical_key=existing_key,
            canonical_name=existing.name if existing is not None else clean_name,
            aliases=all_aliases,
            description=description,
        )

        save_path = ""
        if link_result.get("rewrites") or link_result.get("appended_line"):
            save_path = _save_model(
                model,
                world_model_data_dir,
                game_state=game_state,
                checkpoint_name=checkpoint_name,
            )

        return {
            "success": True,
            "created": False,
            "key": existing_key,
            "item": existing.to_record() if existing else None,
            "reason": f"Item matching '{clean_name}' already exists as '{existing_key}'.",
            "location_memory_link": {
                "rewrites": link_result.get("rewrites", 0),
                "appended_line": link_result.get("appended_line", ""),
            },
            "save_path": save_path,
        }

    # Per-turn cap
    counts = _get_turn_creation_counts(game_state)
    if counts["items"] >= MAX_ITEM_CREATIONS_PER_TURN:
        return {
            "success": False,
            "reason": (
                f"Per-turn item creation cap ({MAX_ITEM_CREATIONS_PER_TURN}) reached. "
                "Cannot create more items this turn."
            ),
            "retryable": False,
        }

    item_key = _unique_key(model, _slug(clean_name))

    normalized_kind = str(holder_kind or "location").strip().lower()
    if normalized_kind not in {"location", "entity"}:
        normalized_kind = "location"

    resolved_holder_key = ""
    if holder_key:
        if normalized_kind == "location":
            resolved_holder_key = _resolve_location_candidate(model, holder_key)
        elif normalized_kind == "entity":
            resolved_holder_key = _resolve_entity_candidate(model, holder_key, game_state=game_state)

    if not resolved_holder_key:
        normalized_kind = "location"
        resolved_holder_key = _resolve_location_candidate(model, game_state.player_location)
    if not resolved_holder_key:
        resolved_holder_key = game_state.player_location
    if not resolved_holder_key:
        resolved_holder_key = model.starting_location

    item = Item.from_record(
        {
            "key": item_key,
            "name": clean_name,
            "description": str(description or "").strip(),
            "holder_kind": normalized_kind,
            "holder_key": resolved_holder_key,
            "portable": bool(portable),
            "tags": [str(t) for t in (tags or [])],
        }
    )
    model.add_item(item)
    model.sync_actor_inventories()

    # Link any prior location memory sentences that described this item
    # (e.g. "a bloodied knife rests on the table") to the new canonical key,
    # append an announcement line, and seed the item with the origin
    # description.
    all_aliases = [clean_name] + (list(aliases) if aliases else [])
    link_result = _link_location_memory_for_new_object(
        model,
        game_state,
        canonical_key=item_key,
        canonical_name=clean_name,
        aliases=all_aliases,
        description=description,
    )
    matched = list(link_result.get("matched_sentences") or [])
    if matched:
        existing_memory = set(item.memory.sentences)
        carried_over: list[str] = []
        for sentence in matched:
            if sentence and sentence not in existing_memory:
                carried_over.append(
                    f"Origin (from location memory): {sentence}"
                )
                existing_memory.add(sentence)
        if carried_over:
            item.memory.add_sentences(carried_over)

    errors = model.validate()
    if errors:
        return {"success": False, "errors": errors, "retryable": False}

    save_path = _save_model(
        model,
        world_model_data_dir,
        game_state=game_state,
        checkpoint_name=checkpoint_name,
    )

    counts["items"] += 1

    register_entity_aliases(game_state, item_key, all_aliases)

    return {
        "success": True,
        "created": True,
        "key": item_key,
        "item": item.to_record(),
        "save_path": save_path,
        "location_memory_link": {
            "rewrites": link_result.get("rewrites", 0),
            "appended_line": link_result.get("appended_line", ""),
            "matched_sentence_count": len(matched),
        },
    }


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

WORLD_MODEL_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_world_story",
            "description": "Read starting story information for the current world model.",
            "parameters": {"type": "object", "properties": {"world_model_data_dir": {"type": "string"}}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_world_story",
            "description": "Update starting story information for the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "starting_location": {"type": "string"},
                    "starting_state": {"type": "string"},
                    "beat_list": {"type": "array", "items": {"type": "string"}},
                    "world_model_data_dir": {"type": "string"},
                    "checkpoint_name": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_world_locations",
            "description": "List all locations in the current world model.",
            "parameters": {"type": "object", "properties": {"world_model_data_dir": {"type": "string"}}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_world_location",
            "description": "Read a single location from the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_key": {"type": "string"},
                    "world_model_data_dir": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_world_location",
            "description": "Create or update a location in the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_key": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "connections": {"type": "array", "items": {"type": "string"}},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "world_model_data_dir": {"type": "string"},
                    "checkpoint_name": {"type": "string"},
                },
                "required": ["location_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "connect_world_locations",
            "description": "Connect two locations in the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_key": {"type": "string"},
                    "other_location_key": {"type": "string"},
                    "bidirectional": {"type": "boolean"},
                    "world_model_data_dir": {"type": "string"},
                    "checkpoint_name": {"type": "string"},
                },
                "required": ["location_key", "other_location_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_world_scene",
            "description": "Get a scene snapshot from the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location_key": {"type": "string"},
                    "world_model_data_dir": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_world_entities",
            "description": "List actors in the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string"},
                    "world_model_data_dir": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_world_entity",
            "description": "Read a single actor from the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_key": {"type": "string"},
                    "world_model_data_dir": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_world_entity",
            "description": "Create or update an actor in the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_key": {"type": "string"},
                    "name": {"type": "string"},
                    "entity_type": {"type": "string"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "skills": {"type": "object"},
                    "stats": {"type": "object"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "memory": {"type": "array", "items": {"type": "string"}},
                    "world_model_data_dir": {"type": "string"},
                    "checkpoint_name": {"type": "string"},
                },
                "required": ["entity_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_world_entity",
            "description": "Move an actor to a different location in the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_key": {"type": "string"},
                    "location_key": {"type": "string"},
                    "world_model_data_dir": {"type": "string"},
                    "checkpoint_name": {"type": "string"},
                },
                "required": ["entity_key", "location_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_world_items",
            "description": "List items in the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "holder_kind": {"type": "string"},
                    "holder_key": {"type": "string"},
                    "world_model_data_dir": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_world_item",
            "description": "Read a single item from the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_key": {"type": "string"},
                    "world_model_data_dir": {"type": "string"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_world_item",
            "description": "Create or update an item in the current world model.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_key": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "holder_kind": {"type": "string"},
                    "holder_key": {"type": "string"},
                    "portable": {"type": "boolean"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "world_model_data_dir": {"type": "string"},
                    "checkpoint_name": {"type": "string"},
                },
                "required": ["item_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_world_item",
            "description": (
                "Move an existing item to a different location or entity holder. "
                "Use this in Phase 2 when a player picks up an item that was "
                "already in the world model."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_key": {"type": "string", "description": "Key of the item to move."},
                    "holder_kind": {"type": "string", "enum": ["location", "entity"], "description": "Whether the new holder is a location or an entity."},
                    "holder_key": {"type": "string", "description": "Key of the new holder."},
                    "world_model_data_dir": {"type": "string"},
                    "checkpoint_name": {"type": "string"},
                },
                "required": ["item_key", "holder_kind", "holder_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_world_model",
            "description": "Validate world-model references and structure.",
            "parameters": {"type": "object", "properties": {"world_model_data_dir": {"type": "string"}}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_npc",
            "description": (
                "Create a new NPC in the world model when the player has directly "
                "interacted with a character not yet registered in the system. "
                "Uses find-or-create semantics: returns the existing key if a match "
                "is found rather than creating a duplicate. "
                "ONLY call this when the player explicitly addresses or acts on the "
                "character (talk to, push, examine up-close, attack, etc.). "
                "Do NOT call for flavor characters mentioned in narration who are "
                "never directly engaged. Do NOT create locations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Display name of the NPC (e.g. 'The Scarred Bartender').",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description drawn from narration context.",
                    },
                    "location": {
                        "type": "string",
                        "description": "Location key where the NPC appears. Defaults to the player's current location.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags such as 'bartender' or 'hostile'.",
                    },
                    "aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "All surface forms the narrator or player used for this character "
                            "before it was created (e.g. 'the man in the corner', 'scarred man'). "
                            "These are registered for future input resolution."
                        ),
                    },
                    "memory_seeds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional seed memories for the NPC drawn from narration.",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_item",
            "description": (
                "Create a new item in the world model when the player has directly "
                "interacted with an object not yet registered in the system. "
                "Uses find-or-create semantics: returns the existing key if a match "
                "is found rather than creating a duplicate. "
                "ONLY call this when the player explicitly addresses or acts on the "
                "object (examine, take, use, destroy, etc.). "
                "Do NOT call for scene-dressing objects the player ignores. "
                "If the player is taking the item, pass holder_kind='entity' and "
                "holder_key='Player' to place it in the player's inventory."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Display name of the item (e.g. 'Bloodied Knife').",
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description from narration context.",
                    },
                    "holder_kind": {
                        "type": "string",
                        "enum": ["location", "entity"],
                        "description": "Whether the item is at a location or held by an entity. Defaults to 'location'.",
                    },
                    "holder_key": {
                        "type": "string",
                        "description": "Key of the location or entity holding the item. Defaults to current player location.",
                    },
                    "portable": {
                        "type": "boolean",
                        "description": "Whether the item can be picked up. Defaults to true.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "aliases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Surface forms used for this object before creation "
                            "(e.g. 'the painting', 'old portrait'). Registered for future resolution."
                        ),
                    },
                },
                "required": ["name"],
            },
        },
    },
]


def execute_world_model_tool(
    tool_name: str,
    arguments: dict[str, Any],
    game_state: GameState | None = None,
) -> dict[str, Any]:
    if tool_name == "get_world_story":
        return get_world_story(game_state=game_state, **arguments)
    if tool_name == "write_world_story":
        return write_world_story(game_state=game_state, **arguments)
    if tool_name == "list_world_locations":
        return list_world_locations(game_state=game_state, **arguments)
    if tool_name == "get_world_location":
        return get_world_location(game_state=game_state, **arguments)
    if tool_name == "upsert_world_location":
        return upsert_world_location(game_state=game_state, **arguments)
    if tool_name == "connect_world_locations":
        return connect_world_locations(game_state=game_state, **arguments)
    if tool_name == "get_world_scene":
        return get_world_scene(game_state=game_state, **arguments)
    if tool_name == "list_world_entities":
        return list_world_entities(game_state=game_state, **arguments)
    if tool_name == "get_world_entity":
        return get_world_entity(game_state=game_state, **arguments)
    if tool_name == "upsert_world_entity":
        return upsert_world_entity(game_state=game_state, **arguments)
    if tool_name == "move_world_entity":
        return move_world_entity(game_state=game_state, **arguments)
    if tool_name == "list_world_items":
        return list_world_items(game_state=game_state, **arguments)
    if tool_name == "get_world_item":
        return get_world_item(game_state=game_state, **arguments)
    if tool_name == "upsert_world_item":
        return upsert_world_item(game_state=game_state, **arguments)
    if tool_name == "move_world_item":
        return move_world_item(game_state=game_state, **arguments)
    if tool_name == "validate_world_model":
        return validate_world_model(game_state=game_state, **arguments)
    if tool_name == "create_npc":
        return create_npc(game_state=game_state, **arguments)
    if tool_name == "create_item":
        return create_item(game_state=game_state, **arguments)
    return {"success": False, "reason": f"Unknown world-model tool: {tool_name}"}


__all__ = [
    "MAX_ENTITY_CREATIONS_PER_TURN",
    "MAX_ITEM_CREATIONS_PER_TURN",
    "WORLD_MODEL_TOOL_DEFINITIONS",
    "create_item",
    "create_npc",
    "execute_world_model_tool",
    "get_world_entity",
    "get_world_item",
    "get_world_location",
    "get_world_scene",
    "get_world_story",
    "list_world_entities",
    "list_world_items",
    "list_world_locations",
    "move_world_entity",
    "move_world_item",
    "upsert_world_entity",
    "upsert_world_item",
    "upsert_world_location",
    "validate_world_model",
    "write_world_story",
]

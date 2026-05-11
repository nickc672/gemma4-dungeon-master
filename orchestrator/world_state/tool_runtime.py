from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .entity import (
    BaseEntity,
    DEFAULT_PLAYER_SKILLS,
    DEFAULT_PLAYER_STATS,
    DynamicSentenceMemory,
    Entity,
    Player,
)
from .story import GameState, mark_location_visited, recompute_discovered_locations
from .world_model import WorldModel, build_world_model


SKILL_TO_STAT: Dict[str, str] = {
    "acrobatics": "dexterity",
    "animal_handling": "wisdom",
    "arcana": "intelligence",
    "athletics": "strength",
    "deception": "charisma",
    "history": "intelligence",
    "insight": "wisdom",
    "intimidation": "charisma",
    "investigation": "intelligence",
    "medicine": "wisdom",
    "nature": "intelligence",
    "perception": "wisdom",
    "performance": "charisma",
    "persuasion": "charisma",
    "religion": "intelligence",
    "sleight_of_hand": "dexterity",
    "stealth": "dexterity",
    "survival": "wisdom",
}


def find_route_via_visited(
    model: WorldModel,
    start_key: str,
    destination_key: str,
    visited_locations: set[str],
) -> Optional[List[str]]:
    """
    BFS for the shortest path from start to destination where every
    intermediate node is in visited_locations. 
    """
    start = str(start_key or "").strip()
    destination = str(destination_key or "").strip()
    if not start or not destination:
        return None
    if start == destination:
        return [start]

    start_location = model.get_location(start)
    if start_location is None:
        return None

    if destination in start_location.connections:
        return [start, destination]

    queue: List[tuple[str, List[str]]] = [(start, [start])]
    seen: set[str] = {start}
    while queue:
        node_key, path = queue.pop(0)
        node = model.get_location(node_key)
        if node is None:
            continue
        for neighbor in node.connections:
            neighbor_key = str(neighbor or "").strip()
            if not neighbor_key or neighbor_key in seen:
                continue
            if neighbor_key == destination:
                return path + [neighbor_key]
            if neighbor_key in visited_locations:
                seen.add(neighbor_key)
                queue.append((neighbor_key, path + [neighbor_key]))
    return None

TODO_ACTIVE_STATUSES = {"pending", "in_progress"}
TODO_FINAL_STATUSES = {"done", "skipped", "blocked"}
TODO_ALLOWED_STATUSES = TODO_ACTIVE_STATUSES | TODO_FINAL_STATUSES

ENTITY_MEMORY_SEEDS: Dict[str, List[str]] = {
    "mitch": [
        "Mitch says he found one of the first bloodstains near the Riverside Path before dawn.",
        "Mitch keeps blaming the town wizard, but his story changes when pressed for exact times.",
        "Mitch looks exhausted and jittery, like he has not slept properly in several nights.",
        "Mitch's hands are heavily calloused from woodcutting, and he smells like sap, smoke, and wet earth.",
    ],
}


def normalize_key(text: str) -> str:
    return str(text or "").strip().lower()


def apply_turn_ctx_defaults(ctx: dict[str, Any]) -> dict[str, Any]:
    ctx.setdefault("phase", "")
    ctx.setdefault("todo", [])
    ctx.setdefault("todo_revision", 0)
    ctx.setdefault("todo_summary", "")
    ctx.setdefault("notes", [])
    ctx.setdefault("current_location", "")
    ctx.setdefault("unresolved_interaction_targets", [])
    ctx.setdefault("creation_counts", {"entities": 0, "items": 0})
    return ctx


def entity_registry(game_state: GameState) -> Dict[str, Entity]:
    registry = getattr(game_state, "entity_registry", None)
    if registry is None:
        registry = {}
        setattr(game_state, "entity_registry", registry)
    return registry


def example_memory_seed_registry(game_state: GameState) -> set[str]:
    seeded = getattr(game_state, "_example_memory_seeded_keys", None)
    if seeded is None:
        seeded = set()
        setattr(game_state, "_example_memory_seeded_keys", seeded)
    return seeded


def seed_entity_example_memories(entity: Entity, game_state: GameState) -> None:
    seed_key = normalize_key(entity.key)
    seeds = ENTITY_MEMORY_SEEDS.get(seed_key, [])
    if not seeds:
        return
    seeded = example_memory_seed_registry(game_state)
    if seed_key in seeded:
        return
    existing = set(entity.memory.sentences)
    additions = [sentence for sentence in seeds if sentence not in existing]
    if additions:
        entity.memory.add_sentences(additions)
    seeded.add(seed_key)


def skill_check_log(game_state: GameState) -> List[dict[str, Any]]:
    log = getattr(game_state, "skill_check_log", None)
    if log is None:
        log = []
        setattr(game_state, "skill_check_log", log)
    return log


def _ensure_world_model_player(model: WorldModel, game_state: GameState) -> Entity:
    player = model.get_entity("Player")
    if player is None:
        start_location = model.starting_location or game_state.player_location or "Town Square"
        player = Player(
            key="Player",
            name="Player",
            description="The player character controlled by the user.",
            location=start_location,
            skills=dict(DEFAULT_PLAYER_SKILLS),
            stats=dict(DEFAULT_PLAYER_STATS),
            tags=["player"],
        )
        player.memory.add_sentences(
            [
                "The player is investigating the harbor town mystery.",
                f"The player is currently at {player.location}.",
            ]
        )
        model.add_entity(player)
    elif not player.location:
        player.set_location(model.starting_location or game_state.player_location or "Town Square")
    return player


def _sync_game_state_from_world_model(game_state: GameState, model: WorldModel) -> None:
    player = model.get_entity("Player")
    if player is not None and player.location:
        game_state.player_location = player.location
        if player.location not in game_state.visited_locations:
            game_state.visited_locations.add(player.location)
            recompute_discovered_locations(game_state, model)

    npc_locations: dict[str, str] = {}
    for entity in model.entities.values():
        if entity.entity_type == "npc" and entity.location:
            npc_locations[entity.key] = entity.location
    game_state.npc_locations = npc_locations


def get_runtime_world_model(game_state: GameState) -> WorldModel:
    model = getattr(game_state, "_runtime_world_model", None)
    if not isinstance(model, WorldModel):
        data_dir = getattr(game_state, "_world_model_data_dir", None)
        model = build_world_model(data_dir=data_dir)
        setattr(game_state, "_runtime_world_model", model)

    _ensure_world_model_player(model, game_state)

    for entity in model.entities.values():
        seed_entity_example_memories(entity, game_state)

    model.sync_actor_inventories()
    _sync_game_state_from_world_model(game_state, model)
    setattr(game_state, "entity_registry", model.entities)
    return model


def set_world_checkpoint_root(game_state: GameState, checkpoint_root: Path | str | None) -> None:
    if checkpoint_root is None:
        if hasattr(game_state, "_world_checkpoint_root"):
            delattr(game_state, "_world_checkpoint_root")
        return
    root = Path(checkpoint_root).expanduser().resolve()
    setattr(game_state, "_world_checkpoint_root", str(root))


def get_world_checkpoint_root(game_state: GameState) -> Optional[Path]:
    raw = getattr(game_state, "_world_checkpoint_root", None)
    if not raw:
        return None
    return Path(str(raw)).expanduser().resolve()


def save_runtime_world_checkpoint(game_state: GameState, checkpoint_name: str = "") -> Optional[Path]:
    checkpoint_root = get_world_checkpoint_root(game_state)
    if checkpoint_root is None:
        return None
    model = get_runtime_world_model(game_state)
    return model.save_checkpoint(checkpoint_root, checkpoint_name=checkpoint_name)


def ensure_entity_registry(game_state: GameState) -> Dict[str, Entity]:
    model = get_runtime_world_model(game_state)
    registry = {normalize_key(entity.key): entity for entity in model.entities.values()}
    setattr(game_state, "entity_registry", registry)
    return registry


def find_entity(entity_key: str, game_state: GameState) -> Optional[Entity]:
    registry = ensure_entity_registry(game_state)
    return registry.get(normalize_key(entity_key))


def find_world_object(object_key: str, game_state: GameState) -> Optional[BaseEntity]:
    model = get_runtime_world_model(game_state)
    return model.get_object(object_key)


def entity_public_view(entity: BaseEntity, *, include_memory_preview: bool = False, memory_preview: int = 3) -> dict[str, Any]:
    return entity.to_public_view(
        include_memory_preview=include_memory_preview,
        memory_preview=memory_preview,
    )


def bind_turn_orchestration_ctx(game_state: GameState, ctx: dict[str, Any]) -> None:
    if not isinstance(ctx, dict):
        raise ValueError("ctx must be a dict")
    setattr(game_state, "_turn_orchestration_ctx", apply_turn_ctx_defaults(ctx))


def clear_turn_orchestration_ctx(game_state: GameState) -> None:
    if hasattr(game_state, "_turn_orchestration_ctx"):
        delattr(game_state, "_turn_orchestration_ctx")


def require_turn_orchestration_ctx(game_state: GameState) -> dict[str, Any]:
    ctx = getattr(game_state, "_turn_orchestration_ctx", None)
    if not isinstance(ctx, dict):
        raise RuntimeError("No turn orchestration context is bound to game_state.")
    return apply_turn_ctx_defaults(ctx)


def get_runtime_alias_registry(game_state: GameState) -> Dict[str, str]:
    """Return the mutable alias-to-canonical-key mapping stored on game_state."""
    registry = getattr(game_state, "_runtime_alias_registry", None)
    if registry is None:
        registry = {}
        setattr(game_state, "_runtime_alias_registry", registry)
    return registry


def register_entity_aliases(game_state: GameState, canonical_key: str, aliases: List[str]) -> None:
    """
    Register one or more surface-form aliases for a world object.

    The canonical key itself is always registered so direct key lookups
    through the alias path also work. Existing aliases pointing to a
    different key are silently overwritten by the new canonical key.
    """
    registry = get_runtime_alias_registry(game_state)
    registry[normalize_key(canonical_key)] = canonical_key
    for alias in aliases:
        norm = normalize_key(alias)
        if norm:
            registry[norm] = canonical_key


def resolve_alias(game_state: GameState, name: str) -> Optional[str]:
    """
    Return the canonical world-object key if name is a registered alias,
    or None if no alias mapping exists for the given name.
    """
    registry = get_runtime_alias_registry(game_state)
    return registry.get(normalize_key(name))


__all__ = [
    "DynamicSentenceMemory",
    "Entity",
    "BaseEntity",
    "Player",
    "SKILL_TO_STAT",
    "TODO_ACTIVE_STATUSES",
    "TODO_ALLOWED_STATUSES",
    "TODO_FINAL_STATUSES",
    "apply_turn_ctx_defaults",
    "bind_turn_orchestration_ctx",
    "clear_turn_orchestration_ctx",
    "ensure_entity_registry",
    "entity_public_view",
    "find_entity",
    "find_world_object",
    "find_route_via_visited",
    "get_runtime_alias_registry",
    "get_runtime_world_model",
    "mark_location_visited",
    "normalize_key",
    "recompute_discovered_locations",
    "register_entity_aliases",
    "require_turn_orchestration_ctx",
    "resolve_alias",
    "get_world_checkpoint_root",
    "save_runtime_world_checkpoint",
    "set_world_checkpoint_root",
    "skill_check_log",
]

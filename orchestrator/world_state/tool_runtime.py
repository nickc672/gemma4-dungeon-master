from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .entity import (
    DEFAULT_PLAYER_SKILLS,
    DEFAULT_PLAYER_STATS,
    DynamicSentenceMemory,
    Entity,
)
from .story import GameState
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
        player = Entity(
            key="Player",
            name="Player",
            entity_type="player",
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
        game_state.discovered_keys.add(player.location)

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


def entity_public_view(entity: Entity, *, include_memory_preview: bool = False, memory_preview: int = 3) -> dict[str, Any]:
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


__all__ = [
    "DynamicSentenceMemory",
    "Entity",
    "SKILL_TO_STAT",
    "TODO_ACTIVE_STATUSES",
    "TODO_ALLOWED_STATUSES",
    "TODO_FINAL_STATUSES",
    "bind_turn_orchestration_ctx",
    "clear_turn_orchestration_ctx",
    "ensure_entity_registry",
    "entity_public_view",
    "find_entity",
    "get_runtime_world_model",
    "normalize_key",
    "require_turn_orchestration_ctx",
    "get_world_checkpoint_root",
    "save_runtime_world_checkpoint",
    "set_world_checkpoint_root",
    "skill_check_log",
]

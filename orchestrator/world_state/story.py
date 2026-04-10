from __future__ import annotations

from dataclasses import dataclass, field

from .world_model import WorldModel, build_world_model


@dataclass
class GameState:
    """Mutable runtime session state derived from the authored world model."""

    player_location: str
    discovered_keys: set[str] = field(default_factory=set)
    conversation_history: list[dict] = field(default_factory=list)
    current_beat: int = 0
    quest_flags: dict[str, bool] = field(default_factory=dict)
    npc_locations: dict[str, str] = field(default_factory=dict)


def create_initial_game_state(
    starting_location: str | None = None,
    *,
    world_model: WorldModel | None = None,
    world_model_data_dir: str | None = None,
) -> GameState:
    model = world_model or build_world_model(data_dir=world_model_data_dir)
    initial_location = str(starting_location or model.starting_location or "Town Square").strip() or "Town Square"
    npc_locations = {
        entity.key: entity.location
        for entity in model.entities.values()
        if entity.entity_type == "npc" and entity.location
    }
    return GameState(
        player_location=initial_location,
        discovered_keys={initial_location},
        conversation_history=[],
        current_beat=0,
        quest_flags={},
        npc_locations=npc_locations,
    )


__all__ = ["GameState", "create_initial_game_state"]

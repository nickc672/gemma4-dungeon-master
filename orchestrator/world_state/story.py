from __future__ import annotations

from dataclasses import dataclass, field

from .world_model import WorldModel, build_world_model


@dataclass
class GameState:
    """Mutable runtime session state derived from the authored world model."""

    player_location: str
    visited_locations: set[str] = field(default_factory=set)
    discovered_locations: set[str] = field(default_factory=set)
    conversation_history: list[dict] = field(default_factory=list)
    current_beat: int = 0
    quest_flags: dict[str, bool] = field(default_factory=dict)
    npc_locations: dict[str, str] = field(default_factory=dict)


def recompute_discovered_locations(game_state: GameState, world_model: WorldModel) -> None:
    """
    Recompute discovered_locations from visited_locations.
    """
    discovered: set[str] = set()
    for visited_key in game_state.visited_locations:
        location = world_model.get_location(visited_key)
        if location is None:
            continue
        for connection in location.connections:
            connection_key = str(connection or "").strip()
            if not connection_key:
                continue
            if connection_key in game_state.visited_locations:
                continue
            discovered.add(connection_key)
    game_state.discovered_locations = discovered


def mark_location_visited(
    game_state: GameState,
    location_key: str,
    world_model: WorldModel,
) -> bool:
    """
    Add a location to visited_locations if not already present, then
    refresh the discovered_locations
    """
    key = str(location_key or "").strip()
    if not key:
        return False
    if key in game_state.visited_locations:
        return False
    game_state.visited_locations.add(key)
    recompute_discovered_locations(game_state, world_model)
    return True


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
    state = GameState(
        player_location=initial_location,
        visited_locations={initial_location},
        discovered_locations=set(),
        conversation_history=[],
        current_beat=0,
        quest_flags={},
        npc_locations=npc_locations,
    )
    recompute_discovered_locations(state, model)
    return state


__all__ = [
    "GameState",
    "create_initial_game_state",
    "mark_location_visited",
    "recompute_discovered_locations",
]
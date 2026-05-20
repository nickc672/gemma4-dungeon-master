from __future__ import annotations
from typing import Any, Dict, List
from ..llm_interaction.prompt_builders import PromptState

"""
Builders for the state objects used by the phase runners.

PromptStateBuilder is what used to be StoryEngine._make_state:
it creates a PromptState (the structured payload the prompt builders use)
from the engine's current world, game state, history, beats, and session summary.

build_trace_state_snapshot is the small dict used by the trace logs
to record the scene at the start and end of a turn.
"""


class PromptStateBuilder:
    """
    Creates a PromptState from the live engine.
    """

    def build(self, engine: Any, player_input: str) -> PromptState:

        def apply_relevant_flags(key: str, info: Dict[str, str]) -> Dict[str, str]:
            relevant_flags = {
                flag: val
                for flag, val in engine.game_state.quest_flags.items()
                if key.lower().replace(" ", "_") in flag.lower()
            }
            if relevant_flags:
                info["flags"] = ", ".join(
                    f"{name}={'yes' if value else 'no'}" for name, value in relevant_flags.items()
                )
            return info

        current_location = engine.game_state.player_location
        scene = engine.world.scene_snapshot(current_location)
        scene_actors = [
            key
            for key in scene.get("actors_here", [])
            if str(key).strip() and str(key).strip().lower() != "player"
        ]
        scene_items = [str(key).strip() for key in scene.get("items_here", []) if str(key).strip()]
        connected_locations = [
            str(key).strip() for key in scene.get("connections", []) if str(key).strip()
        ]

        entity_info: Dict[str, Dict[str, str]] = {}

        location = engine.world.get_location(current_location)
        if location is not None:
            entity_info[location.key] = apply_relevant_flags(location.key, {
                "node_type": location.type,
                "connections": ", ".join(location.connections) if location.connections else "none",
                "location": location.key,
                "visited": "yes" if location.key in engine.game_state.visited_locations else "no",
                "discovered": "yes" if location.key in engine.game_state.discovered_locations else "no",
            })

        for key in connected_locations:
            adjacent = engine.world.get_location(key)
            if adjacent is None:
                continue
            entity_info[adjacent.key] = apply_relevant_flags(adjacent.key, {
                "node_type": adjacent.type,
                "connections": ", ".join(adjacent.connections) if adjacent.connections else "none",
                "location": adjacent.key,
                "visited": "yes" if adjacent.key in engine.game_state.visited_locations else "no",
                "discovered": "yes" if adjacent.key in engine.game_state.discovered_locations else "no",
            })

        player = engine.world.get_entity("Player")
        if player is not None:
            player_info = {
                "node_type": player.entity_type,
                "location": player.location,
            }
            if player.inventory:
                player_info["inventory"] = ", ".join(player.inventory)
            entity_info[player.key] = apply_relevant_flags(player.key, player_info)

        for key in scene_actors:
            entity = engine.world.get_entity(key)
            if entity is None:
                continue
            info = {
                "node_type": entity.entity_type,
                "location": entity.location,
            }
            if entity.inventory:
                info["inventory"] = ", ".join(entity.inventory)
            entity_info[entity.key] = apply_relevant_flags(entity.key, info)

        for key in scene_items:
            item = engine.world.get_item(key)
            if item is None:
                continue
            info = {
                "node_type": item.type,
                "location": engine.world.location_for_key(item.key) or item.holder_key,
            }
            if item.holder_kind == "entity":
                info["holder"] = item.holder_key
            entity_info[item.key] = apply_relevant_flags(item.key, info)

        location_memory_lines: List[str] = []
        if location is not None:
            location_memory_lines = [
                str(line).strip()
                for line in list(location.memory.sentences)
                if str(line).strip()
            ]

        return PromptState(
            history_text=engine.history.as_text(limit=6),
            beat_current=engine.beats.progress_text(),
            beat_next=engine.beats.next() or "None",
            beat_guide=", ".join(engine.beats.beats),
            story_status=engine.story_status,
            session_summary=engine.summary.text(),
            player_input=player_input,
            current_location=current_location,
            scene_description=str(scene.get("description") or "Unknown location"),
            connected_locations=connected_locations,
            scene_actors=scene_actors,
            scene_items=scene_items,
            entity_info=entity_info,
            visited_locations=sorted(engine.game_state.visited_locations),
            discovered_locations=sorted(engine.game_state.discovered_locations),
            location_memory=location_memory_lines,
        )


def build_trace_state_snapshot(engine: Any, state: PromptState) -> Dict[str, Any]:
    """
    used for the trace's STATE_BEFORE / STATE_AFTER blocks.
    """
    scene = engine.world.scene_snapshot(engine.game_state.player_location)
    return {
        "beat_current": state.beat_current,
        "beat_next": state.beat_next,
        "beat_guide": state.beat_guide,
        "scene": {
            "current_location": state.current_location,
            "description": state.scene_description,
            "connections": list(scene.get("connections", [])),
            "actors_here": list(scene.get("actors_here", [])),
            "items_here": list(scene.get("items_here", [])),
            "status": state.story_status,
            "session_summary": state.session_summary,
        },
    }


__all__ = ["PromptStateBuilder", "build_trace_state_snapshot"]
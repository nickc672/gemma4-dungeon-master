from __future__ import annotations

from typing import Any, Dict, List

from ..world_state.story import recompute_discovered_locations


def _compact_text(text: str, limit: int = 280) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def build_runtime_state_snapshot(engine: Any) -> dict[str, Any]:
    world = engine.world
    game_state = engine.game_state

    entities: dict[str, dict[str, Any]] = {}
    for entity in sorted(world.entities.values(), key=lambda value: value.key.lower()):
        entities[entity.key] = {
            "entity_type": entity.entity_type,
            "location": entity.location,
            "inventory": list(entity.inventory),
            "memory": list(entity.memory.sentences),
        }

    items: dict[str, dict[str, Any]] = {}
    for item in sorted(world.items.values(), key=lambda value: value.key.lower()):
        items[item.key] = {
            "holder_kind": item.holder_kind,
            "holder_key": item.holder_key,
            "location": world.location_for_key(item.key),
        }

    return {
        "player_location": game_state.player_location,
        "visited_locations": sorted(str(value) for value in game_state.visited_locations),
        "discovered_locations": sorted(str(value) for value in game_state.discovered_locations),
        "quest_flags": dict(sorted(game_state.quest_flags.items())),
        "npc_locations": dict(sorted(game_state.npc_locations.items())),
        "story_status": engine.story_status,
        "session_summary": list(engine.summary.events),
        "entities": entities,
        "items": items,
        "entity_keys": sorted(entities.keys()),
        "item_keys": sorted(items.keys()),
    }


def diff_runtime_state(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_entities = dict(before.get("entities") or {})
    after_entities = dict(after.get("entities") or {})
    before_items = dict(before.get("items") or {})
    after_items = dict(after.get("items") or {})

    # Entity creation / deletion
    before_entity_keys = set(before.get("entity_keys") or before_entities.keys())
    after_entity_keys = set(after.get("entity_keys") or after_entities.keys())
    entities_created = sorted(after_entity_keys - before_entity_keys)
    entities_removed = sorted(before_entity_keys - after_entity_keys)

    # Item creation / deletion
    before_item_keys = set(before.get("item_keys") or before_items.keys())
    after_item_keys = set(after.get("item_keys") or after_items.keys())
    items_created = sorted(after_item_keys - before_item_keys)
    items_removed = sorted(before_item_keys - after_item_keys)

    entity_location_changes: list[dict[str, Any]] = []
    memory_changes: list[dict[str, Any]] = []
    for key in sorted(set(before_entities) | set(after_entities), key=str.lower):
        prev = dict(before_entities.get(key) or {})
        curr = dict(after_entities.get(key) or {})
        if prev.get("location") != curr.get("location"):
            entity_location_changes.append(
                {
                    "entity": key,
                    "entity_type": curr.get("entity_type") or prev.get("entity_type") or "",
                    "before": prev.get("location") or "",
                    "after": curr.get("location") or "",
                }
            )

        before_memory = list(prev.get("memory") or [])
        after_memory = list(curr.get("memory") or [])
        added = [line for line in after_memory if line not in before_memory]
        removed = [line for line in before_memory if line not in after_memory]
        if added or removed:
            memory_changes.append(
                {
                    "entity": key,
                    "added": added,
                    "removed": removed,
                }
            )

    item_holder_changes: list[dict[str, Any]] = []
    for key in sorted(set(before_items) | set(after_items), key=str.lower):
        prev = dict(before_items.get(key) or {})
        curr = dict(after_items.get(key) or {})
        previous_holder = (prev.get("holder_kind") or "", prev.get("holder_key") or "")
        current_holder = (curr.get("holder_kind") or "", curr.get("holder_key") or "")
        if previous_holder != current_holder:
            item_holder_changes.append(
                {
                    "item": key,
                    "before": {
                        "holder_kind": prev.get("holder_kind") or "",
                        "holder_key": prev.get("holder_key") or "",
                    },
                    "after": {
                        "holder_kind": curr.get("holder_kind") or "",
                        "holder_key": curr.get("holder_key") or "",
                    },
                }
            )

    before_visited = set(before.get("visited_locations") or [])
    after_visited = set(after.get("visited_locations") or [])
    before_discovered = set(before.get("discovered_locations") or [])
    after_discovered = set(after.get("discovered_locations") or [])
    before_flags = dict(before.get("quest_flags") or {})
    after_flags = dict(after.get("quest_flags") or {})
    before_npcs = dict(before.get("npc_locations") or {})
    after_npcs = dict(after.get("npc_locations") or {})

    quest_flag_changes = [
        {
            "flag": key,
            "before": before_flags.get(key),
            "after": after_flags.get(key),
        }
        for key in sorted(set(before_flags) | set(after_flags))
        if before_flags.get(key) != after_flags.get(key)
    ]
    npc_location_changes = [
        {
            "npc": key,
            "before": before_npcs.get(key) or "",
            "after": after_npcs.get(key) or "",
        }
        for key in sorted(set(before_npcs) | set(after_npcs))
        if before_npcs.get(key) != after_npcs.get(key)
    ]

    return {
        "player_location": {
            "before": before.get("player_location") or "",
            "after": after.get("player_location") or "",
        },
        "story_status": {
            "before": before.get("story_status") or "",
            "after": after.get("story_status") or "",
        },
        "session_summary": {
            "before": list(before.get("session_summary") or []),
            "after": list(after.get("session_summary") or []),
        },
        "discovered_locations": {
            "added": sorted(after_discovered - before_discovered),
            "removed": sorted(before_discovered - after_discovered),
        },
        "visited_locations": {
            "added": sorted(after_visited - before_visited),
            "removed": sorted(before_visited - after_visited),
        },
        "quest_flag_changes": quest_flag_changes,
        "npc_location_changes": npc_location_changes,
        "entity_location_changes": entity_location_changes,
        "item_holder_changes": item_holder_changes,
        "memory_changes": memory_changes,
        "entities_created": entities_created,
        "entities_removed": entities_removed,
        "items_created": items_created,
        "items_removed": items_removed,
    }


def build_story_status(player_location: str, turn_summary: str, blocked_reason: str) -> str:
    location = str(player_location or "").strip() or "Unknown"
    summary = _compact_text(turn_summary, limit=320)
    blocked = _compact_text(blocked_reason, limit=180)

    if summary and blocked and blocked.lower() not in summary.lower():
        return f"Current location: {location}. Latest resolved state: {summary} Blocked reason: {blocked}"
    if summary:
        return f"Current location: {location}. Latest resolved state: {summary}"
    if blocked:
        return f"Current location: {location}. Latest blocked reason: {blocked}"
    return f"Current location: {location}. No new resolved state was recorded."


def build_turn_memory_entry(
    player_input: str,
    turn_summary: str,
    blocked_reason: str,
) -> str:
    summary = _compact_text(turn_summary, limit=220)
    blocked = _compact_text(blocked_reason, limit=120)
    player_action = _compact_text(player_input, limit=120)

    fragments = [summary] if summary else []
    if blocked and blocked.lower() not in " ".join(fragments).lower():
        fragments.append(f"Blocked: {blocked}")
    if not fragments and player_action:
        fragments.append(f"Player attempted: {player_action}")

    return " ".join(fragment for fragment in fragments if fragment)


def reconcile_turn(
    engine: Any,
    *,
    turn_number: int,
    player_input: str,
    turn_summary: str,
    blocked_reason: str,
    narration: str,
    action_results: list[dict[str, Any]] | None,
    world_before: dict[str, Any],
) -> dict[str, Any]:
    fixes: List[str] = []

    engine.world.sync_actor_inventories()

    player = engine.world.get_entity("Player")
    if player is not None:
        if player.location and player.location != engine.game_state.player_location:
            engine.game_state.player_location = player.location
            fixes.append("Aligned game_state.player_location with the runtime Player entity.")
        elif not player.location and engine.game_state.player_location:
            player.set_location(engine.game_state.player_location)
            fixes.append("Back-filled missing Player. location from game_state.player_location.")

    world_after = build_runtime_state_snapshot(engine)
    diff = diff_runtime_state(world_before, world_after)

    new_story_status = build_story_status(
        player_location=engine.game_state.player_location,
        turn_summary=turn_summary,
        blocked_reason=blocked_reason,
    )
    engine.story_status = new_story_status

    memory_entry = build_turn_memory_entry(
        player_input=player_input,
        turn_summary=turn_summary,
        blocked_reason=blocked_reason,
    )
    if memory_entry:
        engine.summary.add(f"Turn {int(turn_number)}", memory_entry)

    if fixes:
        diff["reconciliation_fixes"] = fixes

    # Surface newly created entities and items in the diff for logging.
    if diff.get("entities_created"):
        diff["reconciliation_notes"] = diff.get("reconciliation_notes") or []
        for key in diff["entities_created"]:
            diff["reconciliation_notes"].append(f"Entity created this turn: {key}")
    if diff.get("items_created"):
        diff["reconciliation_notes"] = diff.get("reconciliation_notes") or []
        for key in diff["items_created"]:
            diff["reconciliation_notes"].append(f"Item created this turn: {key}")

    diff["story_status"] = new_story_status
    return diff

from __future__ import annotations

import unittest

from orchestrator.world_state.entity import BaseEntity, Entity, Player
from orchestrator.world_state.item import Item
from orchestrator.world_state.location import Location
from orchestrator.world_state.world_model import WorldModel


class WorldStateEntityTests(unittest.TestCase):
    def test_locations_items_and_actors_share_base_entity_behavior(self) -> None:
        location = Location("Town Square", "Town Square", "A busy town square.")
        item = Item("Coin", "Coin", "A worn coin.", "location", "Town Square")
        actor = Entity("Ren", "Ren", "npc", "A watch guard.", "Town Square")

        for value in (location, item, actor):
            self.assertIsInstance(value, BaseEntity)
            value.add_memory(f"{value.name} remembers the storm.")
            self.assertEqual(value.memory_count, 1)
            self.assertEqual(value.search_memory("storm")[0].sentence, f"{value.name} remembers the storm.")

        self.assertEqual(location.type, "location")
        self.assertEqual(item.type, "item")
        self.assertEqual(actor.type, "npc")

    def test_world_model_can_retrieve_objects_polymorphically(self) -> None:
        model = WorldModel()
        model.add_object(Location("Town Square", "Town Square", "A busy town square."))
        model.add_object(Entity("Ren", "Ren", "npc", "A watch guard.", "Town Square"))
        model.add_object(Item("Coin", "Coin", "A worn coin.", "location", "Town Square"))

        self.assertIsInstance(model.get_object("Town Square"), BaseEntity)
        self.assertIsInstance(model.get_object("Ren"), BaseEntity)
        self.assertIsInstance(model.get_object("Coin"), BaseEntity)
        self.assertEqual(model.key_kind("Town Square"), "location")
        self.assertEqual(model.key_kind("Ren"), "npc")
        self.assertEqual(model.key_kind("Coin"), "item")
        self.assertEqual([record["type"] for record in model.list_object_records("item")], ["item"])

    def test_player_is_a_first_class_entity_subtype(self) -> None:
        player = Player(
            key="Player",
            name="Player",
            description="The player character.",
            location="Town Square",
        )

        self.assertIsInstance(player, Entity)
        self.assertEqual(player.type, "player")
        self.assertEqual(player.entity_type, "player")
        self.assertIn("player", player.tags)
        self.assertTrue(player.skills)
        self.assertTrue(player.stats)

        loaded = Entity.from_record(
            {
                "key": "Player",
                "name": "Player",
                "entity_type": "player",
                "description": "The player character.",
                "location": "Town Square",
            }
        )
        self.assertIsInstance(loaded, Player)
        self.assertEqual(loaded.type, "player")


if __name__ == "__main__":
    unittest.main()

=================================
DATABASE
=================================

WHAT THIS IS

This folder is a complete second version of the game's data layer, built on top of a Postgres database.

The original project proposal called for four separate databases (for the story, the rules, the characters, and the locations) plus a set of MCP servers that expose those databases as tools the AI could use.
That work was actually done, and it is all here in this folder.

But here is the catch: the live AI Dungeon Master in "orchestrator/" does not use any of it.
The live game loads its world from JSON files instead.

So this folder exists as a complete but disconnected side track:
- AS MCP SERVERS, the code works.
  You can boot Postgres, run the MCP servers, and use the MCP Inspector to browse their tools.
- AS PART OF THE LIVE GAME, none of it is reached.
  Nothing in "orchestrator/" imports anything from this folder.
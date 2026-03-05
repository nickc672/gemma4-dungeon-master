from __future__ import annotations

from .story import GameState
from .tool_runtime import DynamicSentenceMemory, entity_public_view, find_entity


def get_entity_state(
    entity_key: str = "Player",
    include_memory_preview: bool = False,
    memory_preview: int = 3,
    game_state: GameState | None = None,
) -> dict[str, object]:
    if game_state is None:
        return {"success": False, "reason": "Missing game_state context."}

    resolved_entity = str(entity_key or "").strip() or "Player"
    entity = find_entity(resolved_entity, game_state)
    if entity is None:
        return {"success": False, "reason": f"Entity '{entity_key}' not found."}

    return {
        "success": True,
        "entity": entity_public_view(
            entity,
            include_memory_preview=bool(include_memory_preview),
            memory_preview=max(0, int(memory_preview)),
        ),
    }


def retrieve_memory_tool(
    entity_name: str = "Player",
    context: str = "",
    top_n: int = 4,
    game_state: GameState | None = None,
) -> dict[str, object]:
    if game_state is None:
        return {"success": False, "message": "Missing game_state context.", "memories": []}

    resolved_entity = str(entity_name or "").strip() or "Player"
    entity = find_entity(resolved_entity, game_state)
    if entity is None:
        return {
            "success": False,
            "message": f"Entity '{resolved_entity}' is not registered.",
            "memories": [],
        }

    query = str(context or "").strip()
    if not query:
        return {
            "success": True,
            "entity_name": entity.name,
            "memory_backend": DynamicSentenceMemory.backend_status(),
            "memories": [],
            "message": "No context provided for memory retrieval.",
        }

    hits = entity.search_memory(query, top_n=max(1, int(top_n)))
    return {
        "success": True,
        "entity_name": entity.name,
        "memory_backend": DynamicSentenceMemory.backend_status(),
        "memories": [{"sentence": hit.sentence, "score": float(hit.score)} for hit in hits],
    }


def write_memory_tool(
    entity_name: str = "Player",
    memory: str = "",
    relevance: float = 100.0,
    context: str = "",
    game_state: GameState | None = None,
) -> dict[str, object]:
    if game_state is None:
        return {"success": False, "message": "Missing game_state context."}

    resolved_entity = str(entity_name or "").strip() or "Player"
    entity = find_entity(resolved_entity, game_state)
    if entity is None:
        return {
            "success": False,
            "message": f"Entity '{resolved_entity}' is not registered.",
        }

    text = str(memory or context or "").strip()
    if not text:
        return {
            "success": True,
            "entity_name": entity.name,
            "message": "No memory text provided; skipped write.",
            "memory_count": entity.memory_count,
        }

    entity.add_memory(text)
    return {
        "success": True,
        "entity_name": entity.name,
        "memory": text,
        "relevance": float(relevance),
        "memory_count": entity.memory_count,
    }


ENTITY_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_entity_state",
            "description": "Read detailed state variables for an entity (location, skills, stats, memory count).",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_key": {"type": "string", "description": "Entity key or name."},
                    "include_memory_preview": {"type": "boolean"},
                    "memory_preview": {"type": "integer", "minimum": 0, "maximum": 20},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_memory_tool",
            "description": "Retrieve relevant memory snippets for an entity using semantic search when available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {"type": "string", "description": "Entity name or key."},
                    "context": {"type": "string", "description": "Query context for similarity search."},
                    "top_n": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_memory_tool",
            "description": "Write a new memory sentence into an entity memory store.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {"type": "string", "description": "Entity name or key."},
                    "memory": {"type": "string", "description": "Sentence or fact to store."},
                    "context": {"type": "string", "description": "Alias for memory (notebook compatibility)."},
                    "relevance": {"type": "number", "minimum": 0, "maximum": 1000},
                },
                "required": [],
            },
        },
    },
]


__all__ = [
    "ENTITY_TOOL_DEFINITIONS",
    "get_entity_state",
    "retrieve_memory_tool",
    "write_memory_tool",
]

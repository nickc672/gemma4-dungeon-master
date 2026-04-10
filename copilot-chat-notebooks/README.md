# Ollama DM Orchestration Notebooks

These notebooks are portable examples inspired by the tool-calling loop architecture in this repo.

## Files

- `01_ollama_tool_loop_skeleton.ipynb`
  - Minimal iterative loop with verbose live trace: model -> tool calls -> tool results -> repeat.
- `02_hooks_and_exit_conditions.ipynb`
  - Hook controls (`session_start`, `pre_tool_use`, `post_tool_use`, `stop`) with verbose live trace.
- `03_dnd_dm_world_state_engine.ipynb`
  - Engine-style, multi-turn DM with persistent world state, reasoning trace, and full tool logging.
- `04_dnd_skill_check_live_trace.ipynb`
  - High-volume DnD skill-check loop with RNG tool calls and live, detailed tool trace output.
- `05_player_input_rolls_and_agency.ipynb`
  - Agency-first DM loop with DM-style roll timing: forced checks, unsolicited scene checks, and intent checks that wait for `prompt_player_action` before `roll_dice`.
- `06_staged_turn_loop_orchestrator.ipynb`
  - Multi-turn staged orchestrator (`intent -> mechanics -> narration`) with internal tool loops per stage and optional, situational dice resolution.

## Requirements

- Python 3.10+
- `ollama` Python package (already used by this repo's `LLMAdapter`)
- Ollama server reachable by the `ollama` client
  - Local default: `http://localhost:11434`
  - Remote: set `OLLAMA_HOST=http://<host>:11434`
- A model available locally (default in notebooks is `gpt-oss:20b`)

## Notes

- The notebooks now call Ollama through `orchestrator.llm_interaction.adapter.LLMAdapter`.
- They still use Ollama's tool format with JSON schema in `tools`.
- Tool result messages are appended with:
  - `role: "tool"`
  - `tool_name: <tool name>`
  - `content: <json result string>`
- Verbose trace defaults print:
  - assistant content
  - assistant `thinking` text (reasoning stream)
  - raw model response JSON
  - tool-call source, arguments, and results
- You can copy each notebook's core loop and tool registry directly into modules in your Python project.

# Dungeon Master Companion

A local-first, agentic interactive-fiction orchestrator that turns a small open-weight LLM into a competent AI Dungeon Master, plus a closed-world benchmark suite that grades both the LLM and the orchestration code on the same scenarios.

---

## What this project is

Dungeon Master Companion is where **the model runs the system.** Every non-trivial decision in a turn is a tool call the model chooses to make:

- which character to look up
- which memory needs retrieving
- whether the player's words warrant a skill check
- whether something happened worth remembering
- whether the scene calls for a character or item that does not exist yet

The orchestrator's job is to make sure the world the model writes to actually exists, the lookups it asks for are honest, and the mutations it commits are valid.

Each turn runs in three phases, and within each phase the model operates as an autonomous agent in a tool-calling loop.

- **Phase 1 (read and plan).** The model receives the player's input and the current scene. From there it is on its own. It picks read-only tools off the menu - `check_can_interact`, `retrieve_memory_tool`, `list_scene_entities`, `get_world_entity`, `skill_check`, and a dozen others - calls them in whatever order it wants, looks at the results, decides whether it needs more, and only when satisfied finalizes a `turn_summary` and a `narration_focus` for the next phase. A simple "I walk to the tavern" might be one tool call. A turn where the player invokes a memory from three rooms back might be four.
- **Narration (prose).** A second model pass takes those outputs and the recent history and writes the actual second-person prose the player will read. No tools here; this pass is the writer, not the agent.
- **Phase 2 (write and grow).** A third pass takes the summary plus the narration and commits everything that changed. The model picks write tools - `move_to_location`, `move_npc`, `move_world_item`, `write_memory_tool` - and decides what each memory line should say on which entity. If the narration introduced something brand new (a stranger the player just bumped into, an object the scene materialized), the model can call `create_npc` or `create_item` to bring it into the world model properly, with seeded memories and a location, so future turns can find it. The closed-world scorer then verifies both that the right tools were called and that the resulting state mutations match the answer key.

The hard part is **staying grounded.** The model has wide latitude, but the world is the source of truth. If Mara is at the Bar Counter, she is at the Bar Counter; the model cannot wish her elsewhere by writing text that says so. If the player asks about a corridor that does not exist, the model should not invent one - it should retrieve the actual adjacencies and surface the constraint in the narration. Memory works the same way: NPCs and locations carry their own memory streams that the orchestrator hands back to the model on retrieval, and the model writes new memory lines that future turns will read. When the player returns to East Alley, the narrator gets the alley's memory of what happened the last time. When the player asks Mara about the storeroom lock, the planner retrieves Mara's memory of someone testing it. The model uses memory the orchestrator surfaces and writes memory the orchestrator will surface later, instead of trying to remember on its own.

The benchmark in `benchmark/` is the grading system for all of this. It runs the orchestrator through a fixed set of scenarios, records every tool the model called with what arguments, snapshots the world state before and after each turn, scores it against an answer key, and writes a per-model HTML report with leaderboards and case-by-case detail.

The bigger picture for us is what local LLMs can do for **video game NPCs**. Every shipped game today has characters that say the same lines forever. We wanted to prove you can get believable, in-world AI storytelling - characters that actually remember what you did, conversations that fit the world - without retraining a model from scratch and without sending player data to the cloud. Harbor Town is the proof of concept.

---

## Why Gemma 4

The orchestrator was designed around three capabilities that Gemma 4 ships natively: function calling, a long context window, and configurable thinking. The 31B dense flagship is the sweet spot for the project, and the smaller E4B variant runs the same scenarios on a laptop with surprisingly little quality loss.

- **Native function calling is the whole substrate.** Every decision the model makes in a turn lands as a tool call: which character to look up, which memory to retrieve, which dice to roll, which entity to create, what to write to whom. Gemma 4's tool calling produces clean `{"name": ..., "arguments": ...}` structures that drop straight into the agent loop, which means the model can chain several tool calls per turn. The closed-world benchmark scorer then verifies the model picked the *right* tools, not just any tools - which is where weaker function-calling models lose points fast.
- **Long context lets the agent see everything when deciding.** The hard-tier scenarios depend on the model integrating the player input, the visited-location list, an NPC's seeded memory, the conversation history, and the full tool result trace simultaneously before deciding what to do next. Gemma 4's 128K window on the small models and 256K on the medium models means none of that has to be summarized or dropped, so the model's tool choices stay grounded in everything that actually happened.
- **Thinking is a knob the orchestrator can flip.** Gemma 4 31B runs with `<|think|>` enabled in the system prompt when a hard turn warrants deliberation (a confrontation, a code-clue payoff, a decision about whether to spawn a new NPC), and without it when speed matters (a simple move, a brief greeting). The orchestrator can toggle this per-phase, which the benchmark also exercises.

If a 31B-class open-weight model can run this much agentic decision-making locally and still score well on the hard tier of the benchmark, it can run a full interactive-fiction session on consumer hardware with no cloud round-trips. That is the demonstration the project is built to make.

### Why Gemma 4 over the other local models we tried

We made an early call to keep the whole project on local Ollama models. That ruled out anything cloud-dependent and meant we needed something fast enough to feel like a game and accurate enough to not break the game. We ran four models through the full 30-case benchmark to figure out what actually fit:

| Rank | Model                | Mean Score | Total Time | Avg Time/Case | Perfect Cases |
|------|----------------------|------------|------------|---------------|---------------|
| 1    | gemma4:31b           | **0.974**  | 731.1s     | 24.37s        | 25            |
| 2    | gpt-oss:20b          | 0.905      | 326.9s     | 10.89s        | 18            |
| 3    | devstral-small-2:24b | 0.866      | 141.6s     | 4.72s         | 13            |
| 4    | llama3.1:8b          | 0.711      | 151.0s     | 5.03s         | 5             |

Phase-by-phase, Gemma 4 31B scored 0.982 on Phase 1, 0.990 on Narration, and 0.950 on Phase 2 - the only model to break 0.9 on the writer phase, which is exactly where state corruption happens. gpt-oss 20B and llama 3.1 8B were fast on our hardware but dropped or hallucinated tool calls often enough that the game would visibly break mid-session. devstral was decent and quick but well behind on Phase 2.

We also tried **Qwen 3.6**, which got closer to Gemma's accuracy than anything else on the list - but it ran so slowly on our hardware that it was not viable for actual gameplay, so it never made it onto the chart. Yes, Gemma 4 averages ~24s per case versus 10s for gpt-oss. That tradeoff was worth it for us, because the fast models would lie about what just happened in the world. In a story game, waiting a few extra seconds for a turn beats the model silently corrupting your save.

What sealed it in playtesting: Gemma 4 was creative *and* consistent. It would invent new characters that fit the tone of the world, correctly call `create_npc` to register them into memory, and then keep them in character three turns later when the player came back to talk to them. It would also stay inside the bounds of the story instead of going off the rails.

---

## Architecture at a glance

```
                            player input
                                 |
                                 v
            +--------------------+--------------------+
            |               Phase 1                   |
            |    agent loop, read-only tools          |
            |                                         |
            |    model -> tool call -> result --+     |
            |       ^                           |     |
            |       +---------------------------+     |
            |    (repeat until model finalizes)       |
            |                                         |
            |   produces turn_summary, narration_focus|
            +--------------------+--------------------+
                                 |
                                 v
            +--------------------+--------------------+
            |              Narration                  |
            |    single pass, no tools                |
            |    second-person prose, structural rules|
            +--------------------+--------------------+
                                 |
                                 v
            +--------------------+--------------------+
            |               Phase 2                   |
            |    agent loop, write tools              |
            |                                         |
            |    model -> tool call -> result --+     |
            |       ^                           |     |
            |       +---------------------------+     |
            |    (repeat until model finalizes)       |
            |                                         |
            |   commits all mutations to world state  |
            +--------------------+--------------------+
                                 |
                                 v
                       world mutates, next turn
```

Phase 1 and Phase 2 are both agentic. Within each one, the model decides which tools to call, in which order, with which arguments, and when it has enough information to be done. The orchestrator provides the toolbox, enforces the closed-world rules (Phase 1 can only read; Phase 2 can also write and create), and validates that the arguments the model passes refer to things that actually exist. Everything else is the model's call.

Each phase has its own prompt builder (`prompt_builders.py` plus `prompt_texts.py`), its own allowed tool set (`tool_registry.py`), and its own scoring path in `benchmark/metrics.py`. The world itself lives in three plain JSON files (`actors.json`, `locations.json`, `items.json`) plus a small story spec (`story.json`), which makes the setting trivial to fork into a new game.

---

## Quick start

You need Python 3.10 or newer, Ollama 0.22 or newer, and a one-time download of Gemma 4.

**1. Install the Ollama daemon from <https://ollama.com/download>**

```bash
ollama serve &
ollama pull gemma4:31b
```

**2. Install the Python dependencies**

```bash
python3 -m pip install -r requirements.txt
```

**3. Run the benchmark against Gemma 4**

```bash
python3 -m benchmark.runner --model gemma4:31b
```

The runner prints a per-phase score summary, drops a JSON result file and an HTML report into `benchmark/output/`, and tells you the exact paths.

To play an interactive session in the terminal instead of running the graded suite:

```bash
python3 -m cli --model gemma4:31b
```

To play through the Streamlit front end (Dungeon Master's Companion):

```bash
streamlit run streamlit_app.py
```

---

## Project layout

```
harbor-town/
    actors.json              the cast: NPCs, their locations, memories, stats
    locations.json           the world map: rooms, connections, descriptions
    items.json               portable and fixed items, who or where holds them
    story.json               the central mystery and pacing beats
    app_config.json          model defaults, prompt knobs, runtime tuning

    streamlit_app.py         Dungeon Master's Companion player UI
    cli.py                   interactive player loop (one human, one model)
    pipeline.py              StoryEngine: owns the three phases per turn
    phase_one.py             Phase 1 runner (planner)
    narration.py             Narration runner (prose)
    phase_two.py             Phase 2 runner (writer)
    agent_loop.py            multi-turn tool-calling loop used by Phase 1 and 2
    prompt_builders.py       assembles per-phase prompts from world state
    prompt_texts.py          the canonical instruction blocks
    tool_registry.py         which tools each phase is allowed to call
    world_model_tools.py     CRUD tools over the world model
    scene_tools.py           movement, interactability, scene queries
    entity_tools.py          NPC and player memory read and write
    mechanics_tools.py       skill checks, dice rolls
    adapter.py               LLM transport abstraction
    ollama.py                Ollama-specific transport implementation

    benchmark/
        __init__.py                  what the benchmark is and how to run it
        runner.py                    the benchmark loop
        metrics.py                   the scorer: tool calls + state changes
        report.py                    JSON to HTML comparison report
        phase_one_scenarios.py       11 Phase 1 cases, easy to hard
        narration_scenarios.py        9 narration cases, easy to hard
        phase_two_scenarios.py       10 Phase 2 cases, easy to hard
        output/                      per-model JSON + HTML (gitignored)
```

---

## Running the benchmark

The benchmark is the most direct way to see what is changing as you tune prompts, swap models, or extend the tool set.

**All phases, default settings:**

```bash
python3 -m benchmark.runner --model gemma4:31b
```

**Skip the HTML, JSON only (faster iteration while debugging):**

```bash
python3 -m benchmark.runner --model gemma4:31b --no-html
```

**Run a single phase while you debug something:**

```bash
python3 -m benchmark.runner --model gemma4:31b --tests phase_one
```

**Watch the model think out loud:**

```bash
python3 -m benchmark.runner --model gemma4:31b --verbose
```

**Force a specific d20 roll value (default is 10) so `skill_check` cases come out deterministically:**

```bash
python3 -m benchmark.runner --model gemma4:31b --roll-preset 17
```

After running several models, build a single comparison report:

```bash
python3 -m benchmark.report --latest 5
```

That picks the five most recent JSON files in `benchmark/output/` and produces one HTML page with model tabs, a leaderboard, and full case-by-case detail.

A useful sweep across the 30-billion-parameter neighborhood:

```bash
for m in gemma4:31b gpt-oss:20b llama3.1:8b devstral-small-2:24b; do
  python3 -m benchmark.runner --model $m
done
python3 -m benchmark.report --latest 5
```

---

## How the scorer works

For tool calls, the scorer uses a **closed-world rule.** Only the tools listed in `expected_tools_called` (plus the phase's implicit finalize tool) are supposed to be called. Anything else counts as a false positive. Missing an expected tool counts as a false negative. This catches "the model called the right tool but also called four unnecessary ones" and "the model skipped the lookup the scenario was designed to test."

For Phase 2, the scorer also runs a **state-changes layer.** It snapshots the world before the phase runs, snapshots it again after, and diffs the two. The expected mutations (`expected_location_after`, `expected_visited_added`, `expected_memory_writes`, and so on) are compared against the actual diff. This catches the failure mode where the model called `move_to_location` correctly but passed the wrong arguments and nothing actually changed.

Both layers produce TP / FP / FN counts per case, which roll up into mean scores per phase and an overall mean per model. The HTML report shows the breakdown.

---

## Extending the world

The world is intentionally data-driven. Adding a new NPC means appending an entry to `actors.json`; adding a new location means an entry in `locations.json` with a list of connections; adding an item means an entry in `items.json` with a `holder_kind` of either `location` or `entity` and the corresponding `holder_key`. The orchestrator picks them up on the next session with no code changes.

The model can also grow the world at runtime. If the narration in a turn introduces a stranger in the crowd or a charm dangling from a shrine that does not yet exist in the JSON files, Phase 2 can call `create_npc` or `create_item` to bring the new entity into the world model properly - with a location, a description, seeded memories, and (for NPCs) stats and skills. From the next turn forward that entity is queryable like any other, and the benchmark's state-change scorer treats its presence the same way it treats any other mutation. This is what keeps the model from drifting: when it wants to talk about something new, it has to actually create it, and the orchestrator validates that creation against the world model's schema.

Adding a new benchmark case means appending a `PhaseOneCase`, `NarrationCase`, or `PhaseTwoCase` to the relevant scenario file. The existing cases in `benchmark/phase_one_scenarios.py` and friends are the templates; the scoring rules are documented in their dataclass field comments.

Adding a new tool means writing the Python function, registering it in `tool_registry.py`, and deciding whether it is Phase 1 or Phase 2. Phase 1 is read-only by convention; Phase 2 owns all mutations, including spawning new entities.

---

## Requirements

- Python 3.10 or newer (uses PEP 604 union syntax and PEP 585 generic builtins).
- Ollama 0.22 or newer for Gemma 4 support.
- The Python dependencies in `requirements.txt` (the `ollama` client; the Streamlit front end also pulls in `streamlit`).
- For `gemma4:31b` specifically, 24 GB or more of VRAM is comfortable. The E4B variant runs on 6 to 8 GB if you want a laptop-class run.

---

## Submission

The full Gemma 4 Challenge writeup lives at [our DEV submission post](https://dev.to/challenges/google-gemma-2026-05-06).

## License and credits

Original code for the Gemma 4 Challenge, by Nick and Jake. The world data, scenarios, and orchestrator design are original; the Ollama client and Gemma 4 weights are used per their respective licenses (MIT and Apache 2.0).

This project would be much harder without the open-weight model ecosystem - thanks to Google DeepMind for releasing Gemma 4 under Apache 2.0, and to the Ollama team for making local model deployment a single command.

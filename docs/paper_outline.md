# Paper Outline: Procedural Narratives Grounded in Authorial Intent

Working title:
**Procedural Narratives Grounded in Authorial Intent: A Tool-Grounded Architecture for Interactive Storytelling Without Model Fine-Tuning**

## 0. One-Sentence Thesis

This paper argues that interactive narrative systems can preserve authorial intent while allowing player-driven, AI-mediated story unfolding by grounding a language model in structured story state, deterministic tools, staged turn execution, and runtime memory instead of relying on model fine-tuning or weight updates.

## 1. Abstract

TODO: Write this last.

Draft shape:
- Problem: LLM-driven stories are flexible but prone to contradiction, drift, and loss of planned narrative structure.
- Approach: Authors provide a structured world model: story beats, locations, actors, items, starting state, and narrative constraints. The system lets an LLM improvise within that structure through a staged read/mechanics/narrate/write loop.
- Technical contribution: A provider-agnostic orchestration layer that grounds each turn in world-state tools, memory retrieval, validation hooks, state mutation tools, and reconciliation.
- Evaluation: Compare grounded runs against less-structured LLM baselines using narrative fidelity, contradiction rate, state consistency, beat adherence, and player-perceived agency.
- Claim: Authorial intent can be represented as structured runtime context and procedural constraints, allowing open-ended play without supervised training tasks or model fine-tuning.

## 2. Introduction

### 2.1 Motivation

Interactive narrative systems must balance two pressures:
- Player agency: the player should be able to ask unexpected questions, move freely, investigate in different orders, and define their own doctrine for resolving the story.
- Authorial intent: the story should still preserve tone, theme, causal logic, character truth, clues, and planned dramatic escalation.

This repo frames the problem through a tabletop roleplaying game setting, especially a single-player investigative D&D-like session. A human Dungeon Master can improvise while remembering the authored scenario. The system attempts to approximate that division of labor by giving the AI structured access to authored story state and runtime state.

### 2.2 Core Research Problem

How can a generative AI system unfold a procedural narrative while remaining grounded in the author's intended world, plot logic, and dramatic constraints without training a custom model?

### 2.3 Proposed Answer

Instead of teaching the model the story through fine-tuning, the system externalizes authorial intent into:
- A structured world model: `story.json`, `locations.json`, `actors.json`, and `items.json`.
- A beat guide that defines intended progression without hard-locking player action.
- Runtime scene context: current location, actors, items, connections, visited locations, and discovered locations.
- Tool-mediated mechanics for movement, interaction validation, dice rolls, skill checks, memory retrieval, and state mutation.
- A staged turn architecture that separates reading, resolving, narrating, writing, and reconciling state.

## 3. Background and Related Work

TODO: Add citations.

Candidate areas:
- Interactive narrative and drama management.
- Emergent narrative and player agency.
- AI Dungeon Master / TTRPG narrative systems.
- Retrieval-augmented generation and tool-grounded LLMs.
- LLM agents and function calling.
- Model Context Protocol or MCP-like tool interfaces.
- Narrative planning and authorial control.
- Evaluation of narrative coherence, contradiction, and user agency.

Possible framing:
- Prior systems often favor either authored branching structure or open-ended generation.
- Branching systems preserve author control but limit player freedom.
- Pure LLM systems maximize flexibility but lack durable state, rules discipline, and long-range story fidelity.
- This system sits between those poles: the author defines the dramatic substrate, while the LLM performs local improvisation under tool and state constraints.

## 4. System Overview

### 4.1 Design Goal

The design goal is not to create a fully autonomous novelist. It is to create a procedural narrative engine where:
- The author writes a story world and intended arc.
- The player interacts through natural language.
- The model decides how to locally respond.
- The runtime constrains that response using explicit, inspectable state.
- The world changes only through controlled write tools.

### 4.2 Current Story Testbed

Primary scenario:
**Harbor of Broken Mornings**

Core narrative premise:
- A harbor town suffers repeated bloodshed, missing time, and public panic.
- Mitch is emotionally positioned as an urgent witness and possible victim.
- The wizard is framed as a suspect but is also maintaining unstable order.
- The hidden truth connects dissociative violence, memory intervention, institutional denial, and community trauma.

The authored intent is encoded in:
- Starting state: the tone, location, and premise.
- Beat list: seven high-level dramatic beats.
- Location graph: town square, civic spaces, harbor spaces, temple spaces, tavern/underworld spaces, wizard site.
- Actors and items: NPCs, clues, inventories, and scene objects.

### 4.3 High-Level Architecture

Current runtime flow:
1. Build prompt state from the world model and session state.
2. Phase 1 reads state and resolves mechanics using tools.
3. Narration generates player-facing prose from the resolved turn.
4. Phase 2 writes state changes implied by the narration.
5. Reconciliation builds the next story status, session summary, and state diff.

Important implementation modules:
- `orchestrator/runtime_flow/pipeline.py`: `StoryEngine` and staged turn execution.
- `orchestrator/llm_interaction/agent_loop.py`: provider-agnostic tool loop.
- `orchestrator/llm_interaction/prompt_builders.py`: structured prompt construction.
- `orchestrator/llm_interaction/prompt_texts.py`: phase instructions.
- `orchestrator/world_state/world_model.py`: loadable story/world model.
- `orchestrator/world_state/*_tools.py`: read, validation, mechanics, memory, and write tools.
- `orchestrator/runtime_flow/reconciliation.py`: state diffing and post-turn repair.

## 5. Authorial Intent as Runtime Structure

### 5.1 Story Beats as Soft Constraints

The beat list is not a strict branching script. It is pacing guidance. The model sees current and upcoming story pressure, but the player can still investigate in any order.

Example beat categories:
- Establish mood and stakes.
- Introduce emotionally urgent NPC hook.
- Permit free investigation across districts.
- Surface contradictions as pattern.
- Set up confrontation.
- Reveal causal truth.
- Resolve according to player doctrine.

Paper claim:
Beats function as authorial intent anchors rather than rails. They preserve thematic and dramatic direction while allowing procedural traversal.

### 5.2 World Model as Canonical Context

The world model defines what exists before play:
- Locations and graph connections.
- NPCs and their descriptions.
- Items and holders.
- Starting location and story status.
- Beat list.

The model is loaded from JSON and represented as first-class objects: `Location`, `Entity`, `Player`, and `Item`.

Paper claim:
Separating canonical story data from model generation makes narrative facts inspectable, testable, and portable across LLM providers.

### 5.3 Memory as Situated Continuity

Each world object can hold memory sentences:
- Player memory records what the player did or learned.
- NPC memory records interactions from that NPC's perspective.
- Location memory records arrivals, events, and materialized scene details.

Memory retrieval happens during Phase 1 so the narrator receives continuity facts before generating prose.

Paper claim:
Continuity is maintained by runtime object memory, not by trusting the model's chat history alone.

### 5.4 Materialization of Unplanned Detail

The system distinguishes background description from registered world objects.

When a player directly interacts with an unnamed described character or item, Phase 2 may call:
- `create_npc`
- `create_item`

The alias registry and location-memory linker connect phrases like "the man with the scar" to a canonical runtime object.

Paper claim:
This lets the AI generate rich scenes without forcing every background detail into the world model until player attention makes it narratively relevant.

## 6. Turn Architecture

### 6.1 Phase 1: Read and Resolve

Purpose:
- Interpret the player action against the current scene.
- Retrieve relevant state and memory.
- Validate movement or interaction.
- Resolve dice or skill checks.
- Produce a structured turn summary and narration focus.

Available tool categories:
- Scene reads: `get_current_context`, `list_scene_entities`, `get_entity_state`.
- Memory reads: `retrieve_memory_tool`.
- World reads: `get_world_story`, `get_world_location`, `get_world_entity`, etc.
- Validation: `check_can_interact`.
- Mechanics: `skill_check`, `roll_dice`, `get_recent_skill_checks`.
- Terminal handoff: `finalize_turn`.

Design rule:
Phase 1 cannot mutate the world.

### 6.2 Narration: Player-Facing Response

Purpose:
- Generate the actual DM response.
- Use resolved mechanics and Phase 1 tool results.
- Preserve agency by not deciding player actions.
- Avoid asking the player to roll after mechanics already resolved.

The narration step receives:
- Player request.
- Current scene.
- Story status.
- Recent conversation.
- Turn summary.
- Narration focus.
- Tool call log and mechanics results.

Design rule:
Narration describes the resolved action but does not write state.

### 6.3 Phase 2: Write State

Purpose:
- Apply state changes implied by narration.
- Move the player or NPCs.
- Write memories.
- Transfer or create items.
- Materialize directly engaged new NPCs/items.

Available write tools:
- `move_to_location`
- `move_npc`
- `write_memory_tool`
- `move_world_item`
- `create_npc`
- `create_item`
- `finalize_writes`

Design rule:
The model can only change state through controlled tools.

### 6.4 Reconciliation

Purpose:
- Build before/after state snapshots.
- Diff location, memory, item, entity, and quest flag changes.
- Update story status.
- Add compact turn memory to session summary.
- Align player location between world model and game state when needed.

Paper claim:
Reconciliation provides a final deterministic layer that makes state transitions auditable.

## 7. Grounding Without Fine-Tuning

### 7.1 The Problem With Weight-Based Story Knowledge

Fine-tuning or training tasks would make the story implicit in model weights. That creates problems:
- The authored story is hard to inspect.
- Small story edits require data or training updates.
- Multiple stories require multiple training artifacts or broad retraining.
- The model may still hallucinate facts under pressure.

### 7.2 Externalized Story Intelligence

This system keeps story intelligence outside the model:
- World facts live in data files.
- Current scene is computed at runtime.
- Movement is checked by graph reachability.
- Mechanics are resolved by deterministic functions.
- Memory is retrieved from object stores.
- State writes are explicit tool calls.

### 7.3 Model-Agnostic Execution

The `LLMProvider` abstraction supports multiple backends, including local and hosted models.

Paper claim:
Because the constraints live in prompts, tools, and state, the architecture can improve as models improve without rewriting story data or retraining.

## 8. Handling Player Freedom

### 8.1 Natural Language Input

The player can type free-form actions:
- Movement: "I head to the docks."
- Social action: "I ask Mitch what he remembers."
- Investigation: "I inspect the bloodstain."
- Item action: "I take the note."
- Unexpected interaction: "I talk to the woman behind the bar."

The normalization subsystem supports alias matching, gameplay paraphrases, and synonym-based candidate mapping. This should be framed as a companion layer for making player language map more reliably onto canonical concepts.

### 8.2 Movement and Spatial Constraint

Movement is validated using:
- Current location.
- Connected locations.
- Visited locations.
- Reachability through known paths.
- Optional History checks for recalling non-adjacent known routes.

This prevents the narrator from simply inventing arrival at unreachable places.

### 8.3 Open Investigation and Clue Ecology

The test story distributes evidence across:
- Physical traces.
- Administrative records.
- Ritual/arcane traces.
- Behavioral contradictions.

The player does not need to follow one prescribed path. The authored structure is a clue ecology where multiple routes can converge on the same truth model.

### 8.4 Player-Doctrine Endings

The intended ending is not a single correct answer. The player can resolve according to:
- Truth at all costs.
- Stability first.
- Mercy for the broken.
- Accountability with reform.
- Independent intervention.

Paper claim:
Authorial intent is preserved at the level of causal truth and thematic stakes, while player agency is preserved at the level of interpretation and resolution.

## 9. Technical Contributions

### 9.1 Staged Read/Narrate/Write Separation

Separating phases reduces failure modes:
- Read phase gathers facts before prose.
- Narration focuses on player-facing quality.
- Write phase makes state changes explicit.
- Reconciliation audits what changed.

### 9.2 Tool-Grounded Narrative Constraints

The model is not trusted to remember rules or topology unaided. It must use tools for:
- Interactability.
- Movement.
- Skill checks.
- Memory retrieval.
- State mutation.

### 9.3 Runtime Object Memory

Memory belongs to world objects rather than a single global transcript. This supports:
- NPC-specific continuity.
- Location-specific scene history.
- Player-specific self-history.
- Retrieval targeted to the current action.

### 9.4 Lazy World Materialization

Background details become canonical only when player interaction requires it. This avoids over-modeling while still letting the world grow.

### 9.5 Provider-Agnostic Model Layer

The same staged loop can run over multiple LLM providers through a common adapter.

## 10. Evaluation Plan

### 10.1 Research Questions

RQ1: Does tool-grounded state reduce factual contradiction compared with an unconstrained LLM narrator?

RQ2: Does beat-guided world context improve adherence to authored narrative intent without reducing perceived player agency?

RQ3: Does object-level memory improve continuity in repeated NPC and location interactions?

RQ4: Can runtime materialization support unplanned player interactions without causing duplicate or incoherent world objects?

### 10.2 Experimental Conditions

Candidate ablations:
- LLM-only: prompt includes story premise but no structured tools.
- Prompt-only world context: current scene and beat list, but no tool calls or write phase.
- Read tools only: model can inspect state but cannot use controlled write tools.
- Full system: Phase 1, narration, Phase 2, reconciliation, memory, and validation.

### 10.3 Quantitative Metrics

Narrative fidelity:
- Beat adherence rate.
- Reveal ordering violations.
- Theme or tone drift count.

State consistency:
- Invalid movement attempts narrated as successful.
- NPC/item location contradictions.
- Duplicate materialization rate.
- Missing memory writes after non-trivial turns.

Mechanics correctness:
- Skill checks performed when needed.
- Rolls not invented in narration.
- Check outcomes reflected correctly in narration.

Continuity:
- NPC memory retrieval coverage.
- Returning-location continuity coverage.
- Contradictions against stored memory.

Player agency:
- Number of distinct valid paths through the story.
- Ratio of blocked actions with valid world-state reasons.
- Survey score for perceived freedom.

### 10.4 Qualitative Evaluation

Collect:
- Playtest transcripts.
- Player surveys on agency, coherence, and narrative satisfaction.
- Reviewer ratings of story fidelity and character consistency.
- Annotated examples of failures and recoveries.

Questions for players:
- Did the story feel responsive to your choices?
- Did the world feel consistent?
- Did NPCs remember prior interactions?
- Did the mystery remain coherent?
- Did the ending feel like it followed from your decisions?

### 10.5 Example Failure Taxonomy

Potential categories:
- Narrative drift: model introduces facts incompatible with the authored truth model.
- State drift: prose says a change happened but world state does not record it.
- Tool avoidance: model answers without required validation.
- Over-materialization: background flavor becomes unnecessary canonical state.
- Under-materialization: interacted objects or NPCs remain unregistered.
- Memory omission: narrator ignores stored prior interaction.
- False blockage: system blocks a reasonable action due to missing alias or graph data.

## 11. Case Study: Harbor Town Mystery

### 11.1 Authored Intent

The authored intent is not simply "solve the mystery." It includes:
- Slow-burn dread.
- Moral ambiguity.
- Contradictions as evidence, not noise.
- Competing harms: violence, memory manipulation, panic, denial.
- Resolution by player values.

### 11.2 Example Turn Walkthrough

TODO: Insert one real transcript after running the system.

Suggested example:
Player: "I ask Mitch what he saw that night."

Expected system behavior:
1. Phase 1 validates Mitch is present.
2. Phase 1 retrieves Mitch memory about blaming the wizard and shifting timelines.
3. Phase 1 finalizes a summary and narration focus.
4. Narration voices Mitch with inconsistency.
5. Phase 2 writes memory for Player and Mitch.
6. Reconciliation updates story status and session summary.

### 11.3 Example of Grounded Movement

TODO: Insert a movement transcript.

Suggested example:
Player: "I go to the Wizard's House."

Expected system behavior:
- If adjacent or reachable through visited locations, movement can proceed.
- If unknown or unreachable, `check_can_interact` blocks arrival.
- Narration explains the blockage without inventing a path.

### 11.4 Example of Materialization

TODO: Insert a materialization transcript.

Suggested example:
Player: "I talk to the woman behind the bar."

Expected system behavior:
- Phase 1 may record the unresolved target.
- Narration describes a direct interaction.
- Phase 2 creates `The Barkeep` with aliases.
- Location memory links prior descriptive phrase to the canonical key.

## 12. Discussion

### 12.1 What Counts as Authorial Intent?

In this system, authorial intent is represented at several levels:
- World facts: who exists, where they are, what clues mean.
- Causal truth: what is really happening in the story.
- Beat structure: what kind of dramatic progression should occur.
- Tone and theme: how the story should feel.
- Valid resolution space: which endings are thematically coherent.

### 12.2 What the AI Is Allowed to Invent

The model can invent:
- Local phrasing.
- Sensory detail consistent with scene description.
- NPC dialogue consistent with memory and description.
- Minor connective narration.

The model should not invent:
- Canonical truth that contradicts the story model.
- Movement through impossible geography.
- Mechanical outcomes without tools.
- Player actions.
- Major reveal timing outside the authored arc.

### 12.3 Benefits

Potential benefits:
- No model fine-tuning required.
- Story data remains editable by authors.
- State transitions are inspectable.
- Multiple LLM providers can be swapped.
- The system supports emergent player action while preserving narrative constraints.

### 12.4 Limitations

Known limitations to discuss:
- The system still depends on LLM compliance with prompts and tool calls.
- Lexical memory search is currently lightweight and may miss semantically relevant facts.
- Beat advancement is not yet a fully formalized drama-management policy.
- Evaluation requires careful annotation because "good narrative" is partly subjective.
- Tool and prompt complexity may increase latency and implementation burden.
- The current prototype is text-only and single-player.

## 13. Future Work

Potential directions:
- Formal beat advancement and drama-management scoring.
- Stronger semantic memory retrieval.
- Authoring tools for story designers.
- Automated story validation before runtime.
- Multi-player support.
- Richer rule systems.
- Visual graph inspection of story state.
- Exportable story packages.
- More robust evaluation harnesses and benchmark scenarios.

## 14. Conclusion

Draft claim:

The project demonstrates a practical middle path between rigid branching narratives and unconstrained LLM improvisation. By externalizing authorial intent into structured world data, staged tool use, and auditable runtime memory, the system allows a language model to improvise local narrative responses while preserving the story's deeper causal and thematic structure. The central contribution is not a new trained model, but an orchestration architecture for making generative narrative accountable to authored design.

## 15. Figures and Tables to Add

Figure candidates:
- System architecture diagram: Player input -> Phase 1 -> Narration -> Phase 2 -> Reconciliation -> updated world state.
- World model diagram: story, locations, actors, items, memory.
- Harbor town location graph.
- Example turn trace with tool calls.
- Materialization lifecycle diagram.

Table candidates:
- Comparison of LLM-only, prompt-only, read-tools-only, and full-system conditions.
- Tool categories and responsibilities.
- Evaluation metrics and operational definitions.
- Failure taxonomy with examples.

## 16. Glossary

Authorial intent:
The planned facts, themes, dramatic pressures, and valid resolution space supplied by the story author.

Procedural narrative:
A story experience that unfolds dynamically in response to player action rather than through a fixed branch sequence.

World model:
The structured runtime representation of locations, actors, items, story beats, and starting state.

Beat:
A soft dramatic waypoint that guides pacing and escalation without prescribing exact player actions.

Grounding:
Constraining model generation through explicit state, tools, memory, validation, and reconciliation.

Materialization:
The process of converting an unregistered described character or object into a canonical runtime entity after direct player interaction.

Reconciliation:
The post-turn process that compares before/after state, updates story status, and makes state changes auditable.

## 17. Immediate Writing TODOs

- Choose final title.
- Decide whether to frame tool interfaces specifically as MCP or more generally as tool-grounded orchestration.
- Add a real transcript from the Streamlit app or CLI.
- Add one architecture diagram.
- Add related-work citations.
- Define exact evaluation metrics before running playtests.
- Clarify whether the paper is a design paper, systems paper, thesis chapter, or empirical evaluation.

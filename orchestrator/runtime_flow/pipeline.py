from typing import Any, Dict, Sequence, Optional
from .conversation_log import History
from ..world_state.story import StoryGraph, BEAT_LIST, STARTING_STATE
from ..llm_interaction.adapter import LLMAdapter
from .session_state import BeatTracker, SessionSummary, ActiveKeyManager, FocusManager, SnapshotBuilder
from .step_registry import build_steps
from .step import parse_sections
from ..llm_interaction.prompt_builders import (
    PromptState,
    build_intro_prompt,
    build_intent_prompt,
    build_plan_prompt,
    build_validate_prompt,
    build_narrate_prompt,
)
from ..world_state.story import create_initial_game_state
from ..world_state.tools import VALIDATE_TOOLS, execute_tool, move_to_location

class StoryEngine:

    def __init__(
        self,
        *,
        model: str = "glm-4.7-flash:q8_0",
        story_graph: Optional[StoryGraph] = None,
        initial_keys: Optional[Sequence[str]] = None,
        beats: Optional[Sequence[str]] = None,
        starting_state: str = STARTING_STATE,
        verbose: bool = False,
    ) -> None:

        self.history = History()
        self.summary = SessionSummary()
        self.turn_index = 0
        self.story_status = ""

        self.beats = BeatTracker(list(beats or BEAT_LIST))

        self.story = story_graph or StoryGraph(initial_keys=initial_keys)
        self.starting_state = starting_state
        self.current_focus = list(self.story.initial_keys[:1])
        self.discovered_keys = set(self.story.initial_keys)
        self.active_keys = set()

        self.game_state = create_initial_game_state(self.story)

        self.adapter = LLMAdapter(
            model=model,
            default_options={
                "temperature": 0.2,
                "top_p": 0.5,
                "repeat_penalty": 1.0, # No penalty for repeating tokens (deterministic)
                "top_k": 10, # Only consider top 10 most likely tokens (very narrow)
                "min_p": 0.1, # Minimum probability threshold
            },
            stage_options={
                "narrate": {
                    "temperature": 0.75,
                    "top_p": 0.93,
                    "repeat_penalty": 1.15, # Penalize repetition (more varied prose)
                    "top_k": 50, #wider variety
                    "min_p": 0.05, 
                },
            },
            verbose=verbose,
            # force_retry_stage="plan"
        )

        self.steps = build_steps()
        self.focus_manager = FocusManager()
        self.active_manager = ActiveKeyManager()
        self.snapshot_builder = SnapshotBuilder()

        self.active_keys = self.active_manager.refresh(
            self.story,
            self.current_focus,
            beat_text=self.beats.current(),
        )

    # -----------------------

    def _make_state(self, player_input, intent):
        return PromptState(
            history_text=self.history.as_text(limit=8),
            active_keys=sorted(self.active_keys),
            focus=self.current_focus,
            beat_current=self.beats.progress_text(),
            beat_next=self.beats.next() or "None",
            beat_guide=", ".join(self.beats.beats),
            story_status=self.story_status,
            session_summary=self.summary.text(),
            intent=intent,
            player_input=player_input,
        )

    # -----------------------

    def run_turn(self, player_input: str):

        trace = {} if self.adapter.verbose else None

        # -----------------------
        # INTENT
        # -----------------------

        intent_prompt = build_intent_prompt(
            self.history.as_text(limit=6),
            player_input,
        )

        intent, intent_debug = self.steps["intent"].run(
            self.adapter,
            intent_prompt,
        )

        if trace is not None:
            trace["INTENT"] = intent_debug

        # Handle implicit_move by moving player (without changing intent)
        if intent.get("implicit_move") and intent.get("targets"):
            target = intent["targets"][0]
            
            # Check if target is a location
            target_node = self.story.get_node(target)
            if target_node and target_node.node_type.value == "location":
                # Check if player can move there
                move_result = move_to_location(target, self.game_state, self.story)
                
                if move_result["success"]:
                    if self.adapter.verbose:
                        print(f"[INTENT] Implicit move succeeded: moved to {target}")
                    # Update focus immediately
                    self.current_focus = [target]
                else:
                    if self.adapter.verbose:
                        print(f"[INTENT] Implicit move failed: {move_result['reason']}")

        # -----------------------
        # REFRESH ACTIVE KEYS
        # -----------------------

        self.active_keys = self.active_manager.refresh(
            self.story,
            self.current_focus,
            beat_text=self.beats.current(),
        )

        def build_state_snapshot():
            return {
                "beat_current": state.beat_current,
                "beat_next": state.beat_next,
                "beat_guide": state.beat_guide,
                "scene": {
                    "location_focus": state.focus,
                    "active_nodes": sorted(self.active_keys),
                    "status": state.story_status,
                    "session_summary": state.session_summary,
                },
            }
        
        state = self._make_state(player_input, intent)
        if trace is not None:
            trace["STATE_BEFORE"] = build_state_snapshot()

        # -----------------------
        # PLAN
        # -----------------------

        plan_prompt = build_plan_prompt(state)

        plan, plan_debug = self.steps["plan"].run(
            self.adapter,
            plan_prompt,
        )

        if trace is not None:
            trace["PLAN"] = plan_debug

        # -----------------------
        # VALIDATE (with read-only tools)
        # -----------------------

        validate_prompt = build_validate_prompt(state, plan)

        def _validate_tool_executor(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
            return execute_tool(tool_name, arguments, self.game_state, self.story)

        def _validate_stop_hook(assistant_text: str, _stop_hook_active: bool) -> Optional[str]:
            minimal = parse_sections(assistant_text, {"verdict", "advance"})
            verdict_text = minimal.get("verdict", "").strip().lower()
            advance_text = minimal.get("advance", "").strip().lower()

            if verdict_text not in {"approve", "revise"}:
                return "Before completing, output `Verdict: approve | revise`."
            if not (advance_text.startswith("y") or advance_text.startswith("n")):
                return "Before completing, output `Advance: yes | no`."
            return None

        validate_loop = self.adapter.run_tool_loop(
            stage="validate",
            system_prompt=self.steps["validate"].system_prompt,
            messages=[{"role": "user", "content": validate_prompt}],
            tools=VALIDATE_TOOLS,
            tool_executor=_validate_tool_executor,
            max_iterations=8,
            stop_hook=_validate_stop_hook,
        )

        final_validate_content = validate_loop["final_answer"]
        validate_tool_calls = validate_loop["tool_calls"]

        if validate_loop["status"] != "completed" or not final_validate_content.strip():
            if self.adapter.verbose:
                print("[TOOL] Validation loop hit max iterations; forcing final verdict")

            forced_messages = [
                *validate_loop["messages"],
                {
                    "role": "user",
                    "content": (
                        "Finalize now. Do not call tools. "
                        "Return Thoughts, Verdict, Notes, and Advance in the required format."
                    ),
                },
            ]
            response = self.adapter.request_with_tools(
                stage="validate",
                system_prompt=self.steps["validate"].system_prompt,
                messages=forced_messages,
                tools=[],
            )
            final_validate_content = self.adapter._extract_content(response)

        # Parse the validation result
        sections = parse_sections(final_validate_content, {"thoughts", "verdict", "notes", "advance"})

        validator = self.steps["validate"].validator
        if validator:
            try:
                validator(sections)
            except Exception as exc:
                sections.setdefault("verdict", "revise")
                sections.setdefault(
                    "notes",
                    f"Validation output format issue: {exc}. Defaulting to conservative revise.",
                )
                sections.setdefault("advance", "no")

        parsed_result = self.steps["validate"].parser(sections)
        verdict, notes, advance = parsed_result
        
        # structure that matches the expected format with attempts array
        validate_debug = {
            "attempts": [{
                "attempt": 1,
                "prompt": validate_prompt,
                "raw": final_validate_content,
                "sections": sections,
                "parsed": parsed_result,
            }],
            "tool_calls": validate_tool_calls,
            "rounds": validate_loop["rounds"],
            "status": validate_loop["status"],
        }

        if trace is not None:
            trace["VALIDATE"] = validate_debug

        # -----------------------
        # EXECUTE ACTIONS
        # -----------------------

        action_tool_calls = []
        
        if self.adapter.verbose:
            print(f"\n[ACTION] Executing actions based on intent and validation")
        
        # Only execute actions if validation approved
        if verdict.lower() == "approve":
            action = intent.get("action", "").lower()
            targets = intent.get("targets", [])
            
            # Handle movement actions
            if action == "move" and targets:
                target = targets[0]
                
                if self.adapter.verbose:
                    print(f"[ACTION] Attempting to move to {target}")
                
                result = execute_tool("move_to_location", {"location_key": target}, 
                                    self.game_state, self.story)
                
                action_tool_calls.append({
                    "name": "move_to_location",
                    "arguments": {"location_key": target},
                    "result": result
                })
                
                if result.get("success"):
                    new_location = result["new_location"]
                    self.current_focus = [new_location]
                    
                    if self.adapter.verbose:
                        print(f"[ACTION] Movement succeeded, updated focus to {new_location}")
                    
                    # Refresh active keys with new focus
                    self.active_keys = self.active_manager.refresh(
                        self.story,
                        self.current_focus,
                        beat_text=self.beats.current(),
                    )
                else:
                    if self.adapter.verbose:
                        print(f"[ACTION] Movement failed: {result.get('reason')}")
            
                # Other action types can be handled here in the future
                # elif action == "take" and targets:
                #     ...
                # elif action == "use" and targets:
                #     ...
        
        else:
            if self.adapter.verbose:
                print(f"[ACTION] Validation verdict was '{verdict}', skipping action execution")

        # -----------------------
        # REBUILD STATE WITH UPDATED GAME STATE
        # -----------------------

        if self.adapter.verbose:
            print(f"\n[STATE] Rebuilding state with updated game state")
            print(f"[STATE] Player location: {self.game_state.player_location}")
            print(f"[STATE] Current focus: {self.current_focus}")
            print(f"[STATE] Active keys: {sorted(self.active_keys)}")

        state = self._make_state(player_input, intent)  # Fresh state with updated focus!

        if trace is not None:
            trace["STATE_AFTER_ACTION"] = build_state_snapshot()

        # -----------------------
        # NARRATE WITH UPDATED STATE
        # -----------------------

        narrate_prompt = build_narrate_prompt(state, plan, verdict, notes, action_tool_calls)

        if self.adapter.verbose:
            print(f"\n[NARRATE] Generating narrative with updated state")

        # Simple narration - no tool calls needed (actions already executed)
        narrative, narrate_debug = self.steps["narrate"].run(
            self.adapter,
            narrate_prompt,
        )

        if trace is not None:
            trace["ACTION_TOOLS"] = action_tool_calls
            trace["NARRATE"] = narrate_debug

        # -----------------------
        # COMMIT TURN
        # -----------------------

        self.history.add_player_turn(player_input)
        self.history.add_dm_turn(narrative)
        self.summary.add("Recap", narrative)
        self.turn_index += 1

        result = {
            "turn": self.turn_index,
            "narration": {"ic": narrative},
            "intent": intent,
            "beat": self.beats.current(),
            "active_keys": sorted(self.active_keys),
            "focus": self.current_focus,
            "player_location": self.game_state.player_location,
            "tool_calls": action_tool_calls,
        }

        if trace is not None:
            trace["STATE_AFTER"] = build_state_snapshot()
            result["llm_trace"] = trace

        return result

    # -----------------------
    def generate_intro(self):

        state = PromptState(
            history_text=self.history.as_text(limit=4),
            active_keys=sorted(self.active_keys),
            focus=self.current_focus,
            beat_current=self.beats.progress_text(),
            beat_next=self.beats.next() or "None",
            beat_guide=", ".join(self.beats.beats),
            story_status=self.story_status,
            session_summary=self.summary.text(),
            intent={},
            player_input="",
        )

        prompt = build_intro_prompt(state)

        narrative, _ = self.steps["narrate"].run(
            self.adapter,
            prompt,
        )

        self.history.add_dm_turn(narrative)
        self.summary.add("Intro", narrative)

        return {"ic": narrative, "recap": ""}

    # -----------------------

    def snapshot(self):
        return self.snapshot_builder.build(self)

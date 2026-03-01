from __future__ import annotations

import logging
import re
import textwrap
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from .adapter import LLMAdapter, LLMError
from .history import History
from .normalization.normalize_input import InputNormalizer
from .story import BEAT_LIST, STARTING_STATE, StoryGraph


logger = logging.getLogger(__name__)


PLAN_PROMPT = """You are planning the next response in an interactive narrative.
Use the provided story nodes, their connections, and the conversation so far. Respect the player's input, they drive the story forward.

Instructions:
- Think step-by-step about the most grounded reply (write under Thoughts).
- The player must drive all agency and change in the story. Do not take or suggest actions for them.
- Use the current beat as a loose guide; allow the player to diverge if they choose to.
- Capture the actionable plan in 1-3 sentences (write under Plan).
- Do not narrate yet; this is just preparation. 

Format exactly:
Thoughts: <free-form reasoning>
Plan: <concise plan>
"""

VALIDATE_PROMPT = """You are the logic validator.
Examine the proposed plan, story nodes, and conversation.

Instructions:
- Ensure the plan respects the known story information (locks need codes, etc.).
- Confirm it makes sense chronologically and logically.
- Ensure the plan respects the player's input and agency above all else.
- The player must drive all agency and change in the story. Do not take or suggest actions for them.
- Approve only if no conflicts; otherwise request revision.

Format exactly:
Thoughts: <analysis>
Verdict: approve | revise
Notes: <brief justification>
Advance: yes | no
"""

NARRATE_PROMPT = """You are the storyteller.
Use the story nodes, the approved plan, and the validator notes.

Instructions:
- Think privately before writing (Thoughts).
- Produce immersive second-person narration (Narrative). Keep it to prose/dialogue only—no numbered or bulleted options, no menus of actions.
- Do not include any explicit choices. The player will describe their own actions.
- Respect the player's agency. Never take actions for them.
- The player must drive all agency and change in the story. Do not take or suggest any actions for them.

Format exactly:
Thoughts: <hidden reasoning>
Narrative: <story prose>
"""

STATUS_PROMPT = """You are the story state keeper.

Instructions:
- Summarize the current in-world situation in 2-3 sentences, grounded in the story nodes, beats, and recent conversation.
- Emphasize the player's current location/focus and any immediate tensions or open threads.
- Do NOT offer choices or directives; just describe state.
- The player must drive all agency and change in the story. Do not take or suggest actions for them.

Format exactly:
Status: <concise state>
"""

INTENT_PROMPT = """You extract the player's intent.

Instructions:
- Identify the action (move, talk, inspect, wait, meta_question, other).
- List any explicit targets (people/places/things) they mentioned.
- List any explicit refusals (people/places/things they rejected).
- Do not narrate; just fill the fields.

Format exactly:
Action: <single word>
Targets: key one, key two
Refusals: key one, key two
"""

INTRO_PROMPT = """You are setting the scene for an interactive narrative.
Use the provided starting state, active story nodes, and current beat to craft a concise introduction.

Instructions:
- Write in second person, immersive narration.
- Introduce the player's surroundings, and the starting premise of the story without spoiling future events.
- Never assume player actions or decisions.
- Never offer explicit choices; keep it open for the player to act next.
- The player must drive all agency and change in the story. Do not take or suggest actions for them.

Format exactly:
Thoughts: <hidden reasoning>
Narrative: <scene-setting prose>
Recap: <one-line condensation>
"""


@dataclass
class BeatTracker:
    beats: List[str]
    index: int = 0

    def current(self) -> str:
        return self.beats[self.index] if self.beats else ""

    def next(self) -> str:
        if not self.beats:
            return ""
        nxt = self.index + 1
        return self.beats[nxt] if 0 <= nxt < len(self.beats) else ""

    def progress_text(self) -> str:
        if not self.beats:
            return "No beats provided."
        return f"{self.index + 1}/{len(self.beats)}: {self.current()}"

    def advance(self) -> None:
        if self.index + 1 < len(self.beats):
            self.index += 1


class SessionSummary:
    """Compact rolling summary of the session (player + recap highlights)."""

    def __init__(self, max_items: int | None = None, max_chars: int | None = None) -> None:
        self.events: List[str] = []
        self.max_items = max_items
        self.max_chars = max_chars

    def add(self, label: str, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        entry = f"{label}: {cleaned}"
        self.events.append(entry)
        self._trim()

    def text(self) -> str:
        return "\n".join(self.events)

    def _trim(self) -> None:
        if self.max_items is None and self.max_chars is None:
            return
        while True:
            if self.max_items is not None and len(self.events) > self.max_items:
                self.events = self.events[1:]
                continue
            if self.max_chars is not None and len(self.text()) > self.max_chars:
                self.events = self.events[1:]
                continue
            break

@dataclass
class LLMStep:
    name: str
    system_prompt: str
    tags: set[str]
    use_cot: bool = True
    max_attempts: int = 3
    validator: Optional[Callable[[Dict[str, str]], None]] = None
    parser: Optional[Callable[[Dict[str, str]], Any]] = None

    def run(self, adapter: LLMAdapter, payload_text: str) -> tuple[Any, str]:
        attempts: List[str] = []
        tags = set(self.tags)
        if self.use_cot:
            tags = tags | {"thoughts"}
        for idx in range(self.max_attempts):
            raw = adapter.request_text(self.name, self.system_prompt, payload_text)
            sections = _parse_sections(raw, tags)
            if self.validator:
                try:
                    self.validator(sections)
                except Exception as exc:
                    attempts.append(raw)
                    payload_text = payload_text + f"\n\n(Note: last output was invalid: {exc}. Please follow the required format.)"
                    continue
            if self.parser:
                return self.parser(sections), raw
            return sections, raw
        raise LLMError(
            f"Step '{self.name}' failed after {self.max_attempts} attempts. Last output: {attempts[-1] if attempts else '<none>'}"
        )


class Orchestrator:
    def __init__(
        self,
        *,
        model: str = "gpt-oss:20b",
        story_graph: Optional[StoryGraph] = None,
        initial_keys: Optional[Sequence[str]] = None,
        beats: Optional[Sequence[str]] = None,
        starting_state: str = STARTING_STATE,
        verbose: bool = False,
        normalization_top_n: int = 400,
    ) -> None:
        self.history = History(max_turns=None)
        self.starting_state = starting_state
        self.beat_list = list(beats or BEAT_LIST)
        self.beats = BeatTracker(self.beat_list)
        self.summary = SessionSummary()
        self.turn_index: int = 0
        self.story_status: str = ""
        self.last_debug: Dict[str, Dict[str, str]] = {}
        self.last_intent: Dict[str, List[str] | str] = {"action": "", "targets": [], "refusals": []}
        self.last_normalization: Dict[str, object] = {}

        self.story = story_graph or StoryGraph(initial_keys=initial_keys)
        self.normalizer = InputNormalizer.for_story(self.story, synonym_top_n=normalization_top_n)

        self.discovered_keys: set[str] = set(self.story.initial_keys)
        self.current_focus: List[str] = list(self.story.initial_keys[:1])
        self.active_keys: set[str] = set()
        self._refresh_active_keys()
        self.adapter = LLMAdapter(
            model=model,
            default_temperature=0.6,
            stage_temperatures={"narrate": 0.75},
            verbose=verbose,
        )
        self.step_intent = LLMStep(
            name="intent",
            system_prompt=INTENT_PROMPT,
            tags={"action", "targets", "refusals"},
            use_cot=False,
            parser=_parse_intent_step,
        )
        # Define steps
        self.step_focus = LLMStep(
            name="focus",
            system_prompt="",
            tags={"focus"},
            use_cot=False,
            parser=_parse_focus_step,
        )
        self.step_plan = LLMStep(
            name="plan",
            system_prompt=PLAN_PROMPT,
            tags={"plan"},
            use_cot=True,
            parser=lambda sections: sections.get("plan") or "",
        )
        self.step_status = LLMStep(
            name="status",
            system_prompt=STATUS_PROMPT,
            tags={"status"},
            use_cot=True,
            parser=_parse_status_step,
        )
        self.step_validate = LLMStep(
            name="validate",
            system_prompt=VALIDATE_PROMPT,
            tags={"verdict", "notes", "advance"},
            use_cot=True,
            validator=_validate_validation_step,
            parser=lambda sections: (
                sections.get("verdict", "approve"),
                sections.get("notes", ""),
                (sections.get("advance", "no").lower().startswith("y")),
            ),
        )
        self.step_narrate = LLMStep(
            name="narrate",
            system_prompt=NARRATE_PROMPT,
            tags={"narrative"},
            use_cot=True,
            validator=_validate_narration_step,
            parser=_parse_narration_step,
        )

    def run_turn(self, player_input: str) -> Dict[str, object]:
        debug_data: Dict[str, Dict[str, str]] = {}
        normalization = self.normalizer.normalize(player_input, context=self._normalization_context())
        self.last_normalization = normalization
        debug_data["normalization"] = {"prompt": player_input, "raw": str(normalization)}

        # Intent step
        intent_payload = self._build_intent_prompt(player_input, normalization)
        intent, intent_raw = self.step_intent.run(self.adapter, intent_payload)
        debug_data["intent"] = {"prompt": intent_payload, "raw": intent_raw}
        self.last_intent = intent

        # Apply intent to focus
        self._apply_intent_to_focus(intent, player_input)
        self._refresh_active_keys()

        # Focus refinement (optional)
        focus_payload = self._build_focus_prompt(player_input, intent, normalization)
        try:
            focus_keys, focus_raw = self.step_focus.run(self.adapter, focus_payload)
            debug_data["focus"] = {"prompt": focus_payload, "raw": focus_raw}
            if focus_keys:
                self.current_focus = [k for k in focus_keys if k in self.story.by_key]
        except Exception:
            pass
        self._refresh_active_keys()

        # Record player turn
        self.history.add_player_turn(player_input)
        self.summary.add("Player", player_input)

        # Status step (story state)
        try:
            status_prompt = self._build_status_prompt()
            status, status_raw = self.step_status.run(self.adapter, status_prompt)
            self.story_status = status
            debug_data["status"] = {"prompt": status_prompt, "raw": status_raw}
        except Exception:
            self.story_status = self._summary_text()

        # Planning
        plan_prompt = self._build_plan_prompt(player_input, intent, normalization)
        plan, plan_raw = self.step_plan.run(self.adapter, plan_prompt)
        debug_data["plan"] = {"prompt": plan_prompt, "raw": plan_raw}

        # Validation
        validation_prompt = self._build_validate_prompt(player_input, plan, intent, normalization)
        (verdict, notes, advance), validate_raw = self.step_validate.run(self.adapter, validation_prompt)
        debug_data["validate"] = {"prompt": validation_prompt, "raw": validate_raw}
        # If invalid, retry planning once with validator notes
        if str(verdict).lower().startswith("revise"):
            plan, plan_raw = self.step_plan.run(
                self.adapter,
                self._build_plan_prompt(player_input, intent, normalization) + f"\n\nValidator Notes: {notes}",
            )
            validation_prompt = self._build_validate_prompt(player_input, plan, intent, normalization)
            (verdict, notes, advance), validate_raw = self.step_validate.run(self.adapter, validation_prompt)
            debug_data["validate_retry"] = {"prompt": validation_prompt, "raw": validate_raw}
            debug_data["plan_retry"] = {"prompt": plan_prompt, "raw": plan_raw}
        if advance and str(verdict).lower().startswith("approve"):
            self.beats.advance()

        # Narration
        narrate_prompt = self._build_narrate_prompt(player_input, plan, verdict, notes, intent, normalization)
        narrative, narrate_raw = self.step_narrate.run(self.adapter, narrate_prompt)
        debug_data["narrate"] = {"prompt": narrate_prompt, "raw": narrate_raw}
        recap = ""
        lookup_keys: List[str] = []
        focus_keys: List[str] = []

        # Update focus if narrator provided it
        if focus_keys:
            self.current_focus = [k for k in focus_keys if k in self.story.by_key]

        unlocked = self._register_discovery(lookup_keys + focus_keys + self.current_focus)
        self._refresh_active_keys(explicit_keys=lookup_keys + focus_keys)

        # Summarize for memory (internal) using narrator text directly
        self.summary.add("Recap", narrative)

        dm_entry = narrative
        self.history.add_dm_turn(dm_entry)
        self.turn_index += 1
        self.last_debug = debug_data

        return {
            "turn": self.turn_index,
            "plan": plan,
            "validation": {"verdict": verdict, "notes": notes, "advance": advance},
            "narration": {"ic": narrative, "recap": recap},
            "unlocked_keys": unlocked,
            "active_keys": sorted(self.active_keys),
            "focus": list(self.current_focus),
            "discovered_keys": sorted(self.discovered_keys),
            "beat_state": {
                "current_index": self.beats.index,
                "current": self.beats.current(),
                "next": self.beats.next(),
            },
            "session_summary": self.summary.text(),
            "story_status": self.story_status,
            "llm_debug": debug_data,
            "intent": self.last_intent,
            "normalization": normalization,
        }

    def generate_intro(self) -> Dict[str, str]:
        prompt = self._build_intro_prompt()
        intro_raw = self.adapter.request_text("intro", INTRO_PROMPT, prompt)
        narrative, recap, _, _ = _parse_narration(intro_raw)
        dm_entry = f"{narrative}\nRecap: {recap}" if recap else narrative
        self.history.add_dm_turn(dm_entry)
        if recap:
            self.summary.add("Intro", recap)
        return {"ic": narrative, "recap": recap}

    def snapshot(self) -> Dict[str, object]:
        """Return a JSON-serializable snapshot of the current session state."""
        nodes = []
        for key, node in self.story.by_key.items():
            nodes.append(
                {
                    "key": key,
                    "description": node.description,
                    "connections": list(node.connections),
                    "flags": {
                        "active": key in self.active_keys,
                        "focus": key in self.current_focus,
                        "discovered": key in self.discovered_keys,
                    },
                }
            )
        edges = []
        seen_edges = set()
        for key, node in self.story.by_key.items():
            for neighbor in node.connections:
                if neighbor not in self.story.by_key:
                    continue
                edge_key = tuple(sorted((key, neighbor)))
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                edges.append({"src": key, "dst": neighbor})

        history_turns = [{"role": role, "content": content} for role, content in self.history.turns]

        return {
            "turn": self.turn_index,
            "beat_state": {
                "current_index": self.beats.index,
                "current": self.beats.current(),
                "next": self.beats.next(),
            },
            "active_keys": sorted(self.active_keys),
            "focus": list(self.current_focus),
            "discovered_keys": sorted(self.discovered_keys),
            "session_summary": self.summary.text(),
            "story_status": self.story_status,
            "llm_debug": self.last_debug,
            "history": history_turns,
            "nodes": nodes,
            "edges": edges,
            "normalization": self.last_normalization,
        }

    def _normalization_context(self) -> Dict[str, object]:
        return {
            "current_location": self.current_focus[0] if self.current_focus else "",
            "visible_entities": sorted(self.active_keys),
            "recent_entities": list(self.current_focus),
        }

    def _build_plan_prompt(
        self,
        player_input: str,
        intent: Dict[str, Any],
        normalization: Optional[Dict[str, object]] = None,
    ) -> str:
        keys = sorted(self.active_keys)
        beat_text = self._beat_guide()
        summary = self._summary_text()
        intent_block = _format_intent(intent)
        return textwrap.dedent(
            f"""
            # Intent
            {intent_block}

            # Beat
            Current: {self.beats.progress_text()}
            Next: {self.beats.next() or 'None'}
            Guide: {beat_text}

            # Scene
            Location/Focus: {', '.join(self.current_focus) or 'None'}
            Active Nodes: {', '.join(keys) or 'None'}
            Status: {self.story_status or 'Not set'}
            Session Summary: {summary}

            # Recent Conversation
            {self.history.as_text(limit=8) or 'No prior conversation.'}

            {self._format_player_input_for_prompt(player_input, normalization)}
            """
        ).strip()

    def _build_validate_prompt(
        self,
        player_input: str,
        plan: str,
        intent: Dict[str, Any],
        normalization: Optional[Dict[str, object]] = None,
    ) -> str:
        keys = sorted(self.active_keys)
        beat_text = self._beat_guide()
        summary = self._summary_text()
        intent_block = _format_intent(intent)
        return textwrap.dedent(
            f"""
            # Intent
            {intent_block}

            # Beat
            Current: {self.beats.progress_text()}
            Next: {self.beats.next() or 'None'}
            Guide: {beat_text}

            # Scene
            Location/Focus: {', '.join(self.current_focus) or 'None'}
            Active Nodes: {', '.join(keys) or 'None'}
            Status: {self.story_status or 'Not set'}
            Session Summary: {summary}

            # Recent Conversation
            {self.history.as_text(limit=8) or 'No prior conversation.'}

            {self._format_player_input_for_prompt(player_input, normalization)}

            # Proposed Plan
            {plan}
            """
        ).strip()

    def _build_narrate_prompt(
        self,
        player_input: str,
        plan: str,
        verdict: str,
        notes: str,
        intent: Dict[str, Any],
        normalization: Optional[Dict[str, object]] = None,
    ) -> str:
        keys = sorted(self.active_keys)
        beat_text = self._beat_guide()
        summary = self._summary_text()
        intent_block = _format_intent(intent)
        return textwrap.dedent(
            f"""
            # Intent
            {intent_block}

            # Beat
            Current: {self.beats.progress_text()}
            Next: {self.beats.next() or 'None'}
            Guide: {beat_text}

            # Scene
            Location/Focus: {', '.join(self.current_focus) or 'None'}
            Active Nodes: {', '.join(keys) or 'None'}
            Status: {self.story_status or 'Not set'}
            Session Summary: {summary}

            # Recent Conversation
            {self.history.as_text(limit=8) or 'No prior conversation.'}

            {self._format_player_input_for_prompt(player_input, normalization)}

            # Validated Plan
            {plan}

            # Validator
            Verdict: {verdict}
            Notes: {notes}
            """
        ).strip()

    def _build_focus_prompt(
        self,
        player_input: str,
        intent: Dict[str, Any],
        normalization: Optional[Dict[str, object]] = None,
    ) -> str:
        keys = sorted(self.active_keys)
        return textwrap.dedent(
            f"""
            # Intent
            {_format_intent(intent)}

            # Available Nodes
            {', '.join(keys)}

            {self._format_player_input_for_prompt(player_input, normalization)}
            """
        ).strip()

    def _build_summary_prompt(self, player_input: str, narrative: str, recap: str) -> str:
        return textwrap.dedent(
            f"""
            Player said:
            {player_input}

            Narrative given:
            {narrative}

            Recap (if any):
            {recap}
            """
        ).strip()

    def _build_intent_prompt(
        self,
        player_input: str,
        normalization: Optional[Dict[str, object]] = None,
    ) -> str:
        return textwrap.dedent(
            f"""
            # Recent Conversation
            {self.history.as_text(limit=6) or 'No prior conversation.'}

            {self._format_player_input_for_prompt(player_input, normalization)}
            """
        ).strip()

    def _format_player_input_for_prompt(
        self,
        player_input: str,
        normalization: Optional[Dict[str, object]],
    ) -> str:
        lines = [
            "# Player Input (Original)",
            player_input,
        ]
        if not normalization:
            return "\n".join(lines)

        normalized_text = str(normalization.get("normalized_text") or "").strip()
        normalized_intent = normalization.get("normalized_intent") or {}
        action_id = str(normalized_intent.get("action_id") or "None")
        target_ids = normalized_intent.get("target_ids") or []
        targets_text = ", ".join(str(t) for t in target_ids) if target_ids else "None"
        ambiguity_count = len(normalization.get("ambiguities") or [])

        lines.extend(
            [
                "",
                "# Player Input (Normalized)",
                normalized_text or player_input,
                "",
                "# Normalization Hints",
                f"Action ID: {action_id}",
                f"Target IDs: {targets_text}",
                f"Ambiguities: {ambiguity_count}",
            ]
        )
        return "\n".join(lines)

    def _apply_intent_to_focus(self, intent: Dict[str, Any], player_input: str) -> None:
        """
        Use the parsed intent to set the current focus.
        - If action is move/talk/inspect and targets include known nodes, focus them.
        - If refusals include current focus, clear it.
        """
        action = str(intent.get("action") or "").lower()
        targets = [t for t in intent.get("targets", []) if t in self.story.by_key]
        refusals = set(intent.get("refusals", []))

        # If current focus is refused, drop it
        if any(f in refusals for f in self.current_focus):
            self.current_focus = []

        if targets and action in {"move", "talk", "inspect", "other"}:
            self.current_focus = targets[:2]
            return
        if not self.current_focus and targets:
            self.current_focus = targets[:2]
            return

        # heuristic fallback: try to resolve from raw player input
        if action in {"move", "talk", "inspect", "other"}:
            self._resolve_focus_from_player(player_input)
        elif not self.current_focus:
            self._resolve_focus_from_player(player_input)

    def _build_intro_prompt(self) -> str:
        keys = sorted(self.active_keys)
        beat_text = self._beat_guide()
        summary = self._summary_text()
        return textwrap.dedent(
            f"""
            Starting State:
            {self.starting_state}

            Beat Guide:
            {beat_text}

            Current Beat:
            {self.beats.progress_text()}
            Next Beat:
            {self.beats.next() or 'None'}

            Story Nodes:
            {self.story.describe(keys)}

            Connections:
            {self.story.list_connections(keys)}

            Session Summary:
            {summary}

            Conversation So Far:
            {self.history.as_text(limit=4) or 'No prior conversation.'}
            """
        ).strip()

    def _build_status_prompt(self) -> str:
        keys = sorted(self.active_keys)
        return textwrap.dedent(
            f"""
            Current Focus:
            {', '.join(self.current_focus) or 'None'}

            Active Nodes:
            {', '.join(keys)}

            Beat:
            {self.beats.progress_text()}

            Session Summary:
            {self._summary_text()}

            Conversation So Far:
            {self.history.as_text(limit=6) or 'No prior conversation.'}
            """
        ).strip()

    def _beat_guide(self) -> str:
        return ", ".join(self.beat_list) if self.beat_list else "No beats provided."

    def _summary_text(self) -> str:
        return self.summary.text() or "No significant actions yet."

    def _refresh_active_keys(self, explicit_keys: Iterable[str] | None = None) -> List[str]:
        explicit = {k for k in (explicit_keys or []) if k in self.story.by_key}
        focus = [k for k in self.current_focus if k in self.story.by_key]
        if not focus and self.story.initial_keys:
            focus = [self.story.initial_keys[0]]
            self.current_focus = focus

        active: List[str] = []

        def add(key: str) -> None:
            if key and key in self.story.by_key and key not in active:
                active.append(key)

        # Always include focus nodes
        for key in focus:
            add(key)

        # Neighbors of focus nodes
        for key in focus:
            node = self.story.get_node(key)
            if not node:
                continue
            for neighbor in node.connections:
                add(neighbor)

        # Explicit keys (e.g., from Lookup/Focus output)
        for key in explicit:
            add(key)

        # Beat-pinned heuristic: include nodes whose keys appear verbatim in the current beat text
        beat_text = self.beats.current().lower()
        if beat_text:
            for key in self.story.by_key:
                if key.lower() in beat_text:
                    add(key)

        # Cap size; keep focus first, then explicit, then others
        MAX_ACTIVE = 14
        if len(active) > MAX_ACTIVE:
            keep: List[str] = []
            seen = set()
            for key in focus:
                if key not in seen:
                    keep.append(key)
                    seen.add(key)
            for key in explicit:
                if key not in seen:
                    keep.append(key)
                    seen.add(key)
            for key in active:
                if key not in seen:
                    keep.append(key)
                    seen.add(key)
                if len(keep) >= MAX_ACTIVE:
                    break
            active = keep

        self.active_keys = set(active)
        return active

    def _resolve_focus_from_player(self, text: str) -> None:
        """
        Lightweight focus resolver: look for a node name or alias in the player's message.
        If found, shift focus to that node. Otherwise leave focus unchanged.
        """
        lowered = text.lower()
        # common movement verbs to reduce false positives
        verb_patterns = [
            r"go to ([\w' ]+)",
            r"head to ([\w' ]+)",
            r"walk to ([\w' ]+)",
            r"move to ([\w' ]+)",
            r"enter ([\w' ]+)",
            r"toward ([\w' ]+)",
            r"to ([\w' ]+)",
        ]

        candidates: List[str] = []
        for pat in verb_patterns:
            for match in re.finditer(pat, lowered):
                candidates.append(match.group(1).strip())

        # fallback: any node name mentioned explicitly
        for key in self.story.by_key:
            if key.lower() in lowered:
                candidates.append(key.lower())

        if not candidates:
            return

        best = None
        for candidate in candidates:
            best = self._match_candidate_to_node(candidate)
            if best:
                break
        if best:
            self.current_focus = [best]

    def _match_candidate_to_node(self, candidate: str) -> Optional[str]:
        cand = candidate.strip().lower()
        if not cand:
            return None
        # normalize: remove common articles and punctuation
        cand_norm = re.sub(r"[^a-z0-9\s]", "", cand)
        cand_norm = re.sub(r"^(the|a|an)\s+", "", cand_norm).strip()

        alias = self.story.resolve_alias(cand_norm)
        if alias:
            return alias

        # exact match
        for key in self.story.by_key:
            if key.lower() == cand or key.lower() == cand_norm:
                return key

        # substring match heuristic (both directions)
        for key in self.story.by_key:
            key_norm = re.sub(r"[^a-z0-9\s]", "", key.lower()).strip()
            if cand_norm and cand_norm in key_norm:
                return key
            if key_norm and key_norm in cand_norm:
                return key
        return None

    def _expand_from_source(self, keys: Iterable[str]) -> List[str]:
        if not self.story_source:
            return []
        added: List[str] = []
        for key in keys:
            if not key or self.story.get_node(key):
                continue
            try:
                nodes = self.story_source.fetch_node_and_neighbors(key)
            except Exception as exc:
                logger.warning("Lookup for key '%s' failed: %s", key, exc)
                continue
            merged = self.story.upsert_nodes(nodes)
            for node in merged:
                if node.key not in added and node.key not in self.active_keys:
                    added.append(node.key)
        return added

    def _register_discovery(self, keys: Iterable[str]) -> List[str]:
        unlocked: List[str] = []
        for key in keys:
            if key in self.discovered_keys:
                continue
            if key not in self.story.by_key:
                continue
            self.discovered_keys.add(key)
            unlocked.append(key)
        return unlocked


def _parse_plan(raw: str) -> str:
    sections = _parse_sections(raw, {"thoughts", "plan"})
    return sections.get("plan") or raw.strip()


def _parse_validation(raw: str) -> tuple[str, str, bool]:
    sections = _parse_sections(raw, {"thoughts", "verdict", "notes", "advance"})
    verdict = sections.get("verdict", "approve")
    notes = sections.get("notes", "")
    advance_raw = sections.get("advance", "no").lower()
    advance = advance_raw.startswith("y")
    return verdict.strip(), notes.strip(), advance


def _parse_narration(raw: str) -> tuple[str, str, List[str], List[str]]:
    sections = _parse_sections(raw, {"thoughts", "narrative"})
    narrative = sections.get("narrative", raw.strip())
    return narrative.strip(), "", [], []


def _parse_focus_step(sections: Dict[str, str]) -> List[str]:
    focus_raw = sections.get("focus", "")
    return [token.strip() for token in focus_raw.split(",") if token.strip()]


def _parse_narration_step(sections: Dict[str, str]) -> str:
    return sections.get("narrative", "").strip()


def _parse_status_step(sections: Dict[str, str]) -> str:
    return sections.get("status", "").strip()


def _parse_intent_step(sections: Dict[str, str]) -> Dict[str, Any]:
    action = sections.get("action", "").strip()
    targets = [tok.strip() for tok in sections.get("targets", "").split(",") if tok.strip()]
    refusals = [tok.strip() for tok in sections.get("refusals", "").split(",") if tok.strip()]
    return {"action": action, "targets": targets, "refusals": refusals}


def _parse_sections(text: str, tags: set[str]) -> Dict[str, str]:
    collected: Dict[str, List[str]] = {tag: [] for tag in tags}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        matched = None
        for tag in tags:
            prefix = f"{tag}:"
            if lower.startswith(prefix):
                matched = tag
                content = stripped[len(prefix) :].strip()
                collected[tag].append(content)
                current = tag
                break
        if matched is None and current:
            collected[current].append(stripped)
    return {tag: "\n".join(parts).strip() for tag, parts in collected.items() if parts}


# Validators for LLMStep
def _require_focus_keys(sections: Dict[str, str]) -> None:
    if "focus" not in sections or not sections["focus"].strip():
        raise ValueError("Missing Focus section.")


def _validate_validation_step(sections: Dict[str, str]) -> None:
    verdict = sections.get("verdict", "").lower()
    advance = sections.get("advance", "").lower()
    if verdict not in {"approve", "revise"}:
        raise ValueError("Verdict must be approve or revise.")
    if not (advance.startswith("y") or advance.startswith("n") or advance in {"yes", "no"}):
        raise ValueError("Advance must be yes or no.")


def _validate_narration_step(sections: Dict[str, str]) -> None:
    narrative = sections.get("narrative", "")
    if not narrative:
        raise ValueError("Missing Narrative section.")
    # crude guard against numbered choices
    if re.search(r"\b1\)", narrative) or re.search(r"\b2\)", narrative):
        raise ValueError("Narrative contains numbered choices; remove menus/options.")


def _format_intent(intent: Dict[str, Any]) -> str:
    action = intent.get("action") or ""
    targets = ", ".join(intent.get("targets") or [])
    refusals = ", ".join(intent.get("refusals") or [])
    return f"Action: {action}\nTargets: {targets or 'None'}\nRefusals: {refusals or 'None'}"


__all__ = ["Orchestrator"]

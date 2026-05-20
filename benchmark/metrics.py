from __future__ import annotations
import re
import time
from typing import Any, Dict, List, Optional, Set

from orchestrator.runtime_flow.turn_heuristics import _extract_labeled_line, _extract_labeled_block, _tool_call_succeeded
from orchestrator.runtime_flow.reconciliation import diff_runtime_state
from orchestrator.world_state.entity_tools import write_memory_tool as _write_memory_tool_fn
from orchestrator.world_state.turn_tools import finalize_turn as _finalize_turn_fn, finalize_writes as _finalize_writes_fn

WRITE_MEMORY_TOOL_NAME = _write_memory_tool_fn.__name__
FINALIZE_TURN_TOOL_NAME = _finalize_turn_fn.__name__
FINALIZE_WRITES_TOOL_NAME = _finalize_writes_fn.__name__

from .scenarios.phase_one_scenarios import PhaseOneCase
from .scenarios.narration_scenarios import NarrationCase
from .scenarios.phase_two_scenarios import PhaseTwoCase


"""
Scoring and summarisation for the benchmark.

The text helpers and scoring functions here are independent of the
orchestrator's internals. They consume the typed outputs returned by
Phase1Runner, NarrationRunner, and Phase2Runner.

Two layers of TP/FP/FN are produced per scored case:

  function_calls
    Per-tool breakdown of expected vs actual invocations.
      - tp: expected entries that were satisfied
      - fn: expected entries that were not satisfied
      - fp: actual tool names that were not in the expected set
            (closed-world rule; the phase's finalize tool is implicit)

  state_changes  (Phase 2 only)
    Per-mutation breakdown of expected vs actual world-state changes,
    derived from before/after snapshots. Categories tracked: player
    location, NPC positions, quest flags, visited locations, discovered
    locations, and per-entity memory writes.
"""




# ============================================================
# Timer
# ============================================================

class Timer:
    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed = time.perf_counter() - self._start


# ============================================================
# Local helpers
# ============================================================

def _normalize_token(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^[^\w']+|[^\w']+$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _normalize_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = " ".join(_normalize_token(part) for part in text.split(" "))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _has_section_label(raw: str, label: str) -> bool:
    """
    True if `label:` block is present with content.
    """
    return bool(_extract_labeled_block(raw or "", label).strip())


def _sections_in_order(raw: str, first_label: str, second_label: str) -> bool:
    """
    True if `first_label`'s section appears in `raw` before `second_label`'s.
    """
    first = _extract_labeled_block(raw or "", first_label)
    second = _extract_labeled_block(raw or "", second_label)
    if not first.strip() or not second.strip():
        return False
    first_pos = (raw or "").find(first)
    second_pos = (raw or "").find(second)
    if first_pos < 0 or second_pos < 0:
        return False
    return first_pos < second_pos


def _keywords_match(keyword_groups: List[List[str]], text: str) -> bool:
    """All groups must have at least one keyword present (AND of ORs)."""
    n = _normalize_text(text)
    return all(any(kw.lower() in n for kw in group) for group in keyword_groups)


def _expected_tool_matches(expected: Any, called_tools: List[Dict[str, Any]]) -> bool:
    """
    Match an expected entry against the list of actual tool calls.

    Each call must look like {"name": ..., "arguments": {...}} (Phase 1/2 form)
    or {"name": ..., "args": {...}} (old form). Both are accepted.

    `expected` can be:
      - a string: any call with that name satisfies it
      - a dict {"name": "...", "args": {...}}: name must match and all listed
        args must equal in the actual call's arguments
      - a list: OR-group; at least one option must match
    """
    if isinstance(expected, list):
        return any(_expected_tool_matches(opt, called_tools) for opt in expected)

    if isinstance(expected, str):
        name = expected
        expected_args: Dict[str, Any] = {}
    else:
        name = expected.get("name", "")
        expected_args = expected.get("args") or expected.get("arguments") or {}

    for call in called_tools:
        if call.get("name") != name:
            continue
        if not expected_args:
            return True
        actual_args = call.get("arguments") or call.get("args") or {}
        if all(actual_args.get(k) == v for k, v in expected_args.items()):
            return True
    return False


def _format_expected_entry(entry: Any) -> str:
    if isinstance(entry, list):
        return "AnyOf(" + " | ".join(_format_expected_entry(e) for e in entry) + ")"
    if isinstance(entry, str):
        return entry
    name = entry.get("name", "?")
    args = entry.get("args") or entry.get("arguments") or {}
    if args:
        return f"{name}({', '.join(f'{k}={v}' for k, v in args.items())})"
    return name


def _expected_entry_names(entry: Any) -> Set[str]:
    """All tool names that appear within an expected entry (flattens OR groups)."""
    if isinstance(entry, list):
        out: Set[str] = set()
        for opt in entry:
            out |= _expected_entry_names(opt)
        return out
    if isinstance(entry, str):
        return {entry}
    name = entry.get("name", "") if isinstance(entry, dict) else ""
    return {name} if name else set()


def _allowed_tool_names(expected_entries: List[Any]) -> Set[str]:
    """Union of all tool names appearing in any expected entry."""
    allowed: Set[str] = set()
    for entry in expected_entries or []:
        allowed |= _expected_entry_names(entry)
    return allowed


def _function_call_breakdown(
    expected_entries: List[Any],
    called_tools: List[Dict[str, Any]],
    implicit_allowed: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """
    Per-tool TP/FP/FN breakdown of expected vs actual tool calls.

    TP: an expected entry was satisfied by at least one actual call.
    FN: an expected entry was not satisfied.
    FP: an actual tool name is not in the allowed set
        (allowed = names referenced by any expected entry, plus
        implicit_allowed, e.g. the phase's finalize tool).
    """
    implicit_allowed = set(implicit_allowed or ())

    expected_called: List[str] = []
    expected_missing: List[str] = []
    for entry in expected_entries or []:
        label = _format_expected_entry(entry)
        if _expected_tool_matches(entry, called_tools):
            expected_called.append(label)
        else:
            expected_missing.append(label)

    allowed_names = _allowed_tool_names(expected_entries) | implicit_allowed
    seen_names: List[str] = []
    seen_set: Set[str] = set()
    for call in called_tools:
        name = call.get("name", "")
        if not name or name in seen_set:
            continue
        seen_set.add(name)
        seen_names.append(name)

    unexpected_called = [name for name in seen_names if name not in allowed_names]

    return {
        "expected_called": expected_called,
        "expected_missing": expected_missing,
        "unexpected_called": unexpected_called,
        "allowed_names": sorted(allowed_names),
        "tp": len(expected_called),
        "fn": len(expected_missing),
        "fp": len(unexpected_called),
    }


def _extract_corrections(rounds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pull response-hook rejections out of the agent-loop round records."""
    out: List[Dict[str, Any]] = []
    for i, rnd in enumerate(rounds or []):
        reason = rnd.get("response_block_reason") or ""
        if reason:
            out.append({"iteration": rnd.get("iteration", i), "reason": reason})
    return out


# ============================================================
# Phase 1 scoring
# ============================================================

def score_phase_one(
    case: PhaseOneCase,
    finalize_payload: Optional[Dict[str, Any]],
    phase_one_tool_calls: List[Dict[str, Any]],
    loop_result: Dict[str, Any],
    elapsed: float,
    iterations: int,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    finalize_payload = finalize_payload or {}

    # Detect "finalize was called" by checking the tool-call trace, not by
    # inspecting payload contents.
    finalize_called = any(
        c.get("name") == FINALIZE_TURN_TOOL_NAME and _tool_call_succeeded(c)
        for c in phase_one_tool_calls
    )
    blocked = bool(str(finalize_payload.get("blocked_reason") or "").strip())

    # Convert phase_one_tool_calls into the {name, arguments} shape used here.
    called_tools = [
        {"name": c.get("name", ""), "arguments": c.get("arguments") or {}}
        for c in phase_one_tool_calls
    ]
    called_names = sorted({c["name"] for c in called_tools if c["name"]})

    # Closed-world function-call breakdown.
    fn_breakdown = _function_call_breakdown(
        case.expected_tools_called,
        called_tools,
        implicit_allowed={FINALIZE_TURN_TOOL_NAME},
    )
    expected_tools_ok = fn_breakdown["fn"] == 0
    no_unexpected_tools = fn_breakdown["fp"] == 0

    finalize_ok = finalize_called == case.expect_finalize
    blocked_ok = blocked == case.expect_blocked

    summary_text = str(finalize_payload.get("turn_summary") or "")
    narration_focus_text = str(finalize_payload.get("narration_focus") or "")

    summary_keywords_ok = (
        _keywords_match(case.expected_turn_summary_keywords, summary_text)
        if case.expected_turn_summary_keywords else True
    )
    focus_keywords_ok = (
        _keywords_match(case.expected_narration_focus_keywords, narration_focus_text)
        if case.expected_narration_focus_keywords else True
    )

    iterations_ok = True
    if case.max_iterations > 0:
        iterations_ok = iterations <= case.max_iterations

    fields: List[bool] = [finalize_ok, blocked_ok, expected_tools_ok, no_unexpected_tools]
    if case.expected_turn_summary_keywords:
        fields.append(summary_keywords_ok)
    if case.expected_narration_focus_keywords:
        fields.append(focus_keywords_ok)
    if case.max_iterations > 0:
        fields.append(iterations_ok)

    return {
        "case_id": case.id,
        "case_tags": case.tags,
        "description": case.description,
        "player_input": case.player_input,
        "finalize_called": finalize_called,
        "finalize_ok": finalize_ok,
        "blocked": blocked,
        "blocked_ok": blocked_ok,
        "expected_tools": [_format_expected_entry(e) for e in case.expected_tools_called],
        "actual_tools": called_names,
        "expected_tools_ok": expected_tools_ok,
        "no_unexpected_tools": no_unexpected_tools,
        "function_calls": fn_breakdown,
        "turn_summary": summary_text,
        "narration_focus": narration_focus_text,
        "blocked_reason": str(finalize_payload.get("blocked_reason") or ""),
        "summary_keywords_ok": summary_keywords_ok,
        "expected_summary_keywords": case.expected_turn_summary_keywords,
        "focus_keywords_ok": focus_keywords_ok,
        "expected_focus_keywords": case.expected_narration_focus_keywords,
        "iterations": iterations,
        "iterations_ok": iterations_ok,
        "expected_max_iterations": case.max_iterations,
        "elapsed_s": round(elapsed, 3),
        "loop_status": loop_result.get("status", ""),
        "raw_final": loop_result.get("final_answer", ""),
        "all_rounds": loop_result.get("rounds", []),
        "corrections": _extract_corrections(loop_result.get("rounds", [])),
        "correction_count": len(_extract_corrections(loop_result.get("rounds", []))),
        "tool_trace": phase_one_tool_calls,
        "error": error,
        "all_correct": all(fields),
        "score": round(sum(float(f) for f in fields) / len(fields), 3) if fields else 0.0,
    }


# ============================================================
# Narration scoring
# ============================================================

_SECOND_PERSON = re.compile(r"\byou\b", re.IGNORECASE)
_NUMBERED_CHOICES = re.compile(
    r"(^\s*\d+[\)\.]\s|\b(?:option|choice)\s+\d)",
    re.IGNORECASE | re.MULTILINE,
)
_AGENCY_TAKEN = re.compile(
    r"\byou decide to\b|\byou choose to\b|\byou will\b|\byou must\b",
    re.IGNORECASE,
)
_THE_PLAYER = re.compile(r"\bthe player\b", re.IGNORECASE)

_DEFAULT_CONCISE_MAX = 200
_DEFAULT_MINIMUM_LENGTH = 50


def _parse_check_param(check: str, default: int) -> tuple[str, int]:
    if ":" in check:
        name, _, raw = check.partition(":")
        try:
            return name.strip(), int(raw.strip())
        except ValueError:
            return check, default
    return check, default


_DIALOGUE_QUOTE_CHARS = frozenset({'"', '\u201c', '\u201d'})


def _strip_dialogue(text: str) -> str:
    """
    Return `text` with everything inside double-quoted speech removed.
    """
    if not text:
        return ""
    inside = False
    out: List[str] = []
    for ch in text:
        if ch in _DIALOGUE_QUOTE_CHARS:
            inside = not inside
            continue
        if not inside:
            out.append(ch)
    return "".join(out)


def _has_bare_first_person_i(text: str) -> bool:
    """
    True if a bare 'I' appears in narrator prose (outside dialogue).

    Characters speaking in first person are allowed; only the narrator
    using a bare 'I' counts as a violation. Dialogue is excised via
    `_strip_dialogue` before the search.
    """
    if not text:
        return False
    return bool(re.search(r"\bI\b", _strip_dialogue(text)))


def _location_mentioned(location_key: str, text: str) -> bool:
    text_lower = (text or "").lower()
    key_lower = (location_key or "").lower()
    if not key_lower:
        return True
    if key_lower in text_lower:
        return True
    stop = {"the", "a", "an", "of", "at", "in", "on", "to", "and", "or", "-"}
    words = [w for w in re.split(r"[\s\-]+", key_lower) if w not in stop and len(w) > 2]
    return any(w in text_lower for w in words)


def score_narration(
    case: NarrationCase,
    narrative: str,
    raw_output: str,
    elapsed: float,
    attempts: int,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    word_count = len((narrative or "").split())
    thoughts_text = _extract_labeled_block(raw_output, "Thoughts")

    checks: Dict[str, bool] = {}
    for raw_check in case.checks:
        check, param = _parse_check_param(raw_check, 0)

        if check == "has_two_sections":
            checks[raw_check] = (
                _has_section_label(raw_output, "Thoughts")
                and _has_section_label(raw_output, "Narrative")
            )
        elif check == "thoughts_before_narrative":
            checks[raw_check] = _sections_in_order(raw_output, "Thoughts", "Narrative")
        elif check == "thoughts_is_first_person":
            has_i = bool(re.search(r"\bI\b", thoughts_text))
            has_the_player = bool(_THE_PLAYER.search(thoughts_text))
            checks[raw_check] = has_i or has_the_player
        elif check == "second_person":
            checks[raw_check] = bool(_SECOND_PERSON.search(narrative or ""))
        elif check == "no_explicit_choices":
            checks[raw_check] = not bool(_NUMBERED_CHOICES.search(narrative or ""))
        elif check == "minimum_length":
            limit = param if param > 0 else _DEFAULT_MINIMUM_LENGTH
            checks[raw_check] = word_count >= limit
        elif check == "concise":
            limit = param if param > 0 else _DEFAULT_CONCISE_MAX
            checks[raw_check] = word_count <= limit
        elif check == "no_player_agency_taken":
            checks[raw_check] = not bool(_AGENCY_TAKEN.search(narrative or ""))
        elif check == "narrative_no_the_player":
            checks[raw_check] = not bool(_THE_PLAYER.search(narrative or ""))
        elif check == "narrative_no_bare_i":
            checks[raw_check] = not _has_bare_first_person_i(narrative or "")
        elif check == "mentions_current_location":
            checks[raw_check] = _location_mentioned(case.player_location, narrative or "")
        else:
            checks[raw_check] = False

    forbidden_hits: Dict[str, bool] = {}
    for pattern in case.forbidden_patterns or []:
        forbidden_hits[pattern] = bool(re.search(pattern, narrative or "", re.IGNORECASE | re.MULTILINE))
    no_forbidden = not any(forbidden_hits.values())

    fields: List[bool] = list(checks.values())
    if case.forbidden_patterns:
        fields.append(no_forbidden)

    return {
        "case_id": case.id,
        "case_tags": case.tags,
        "description": case.description,
        "player_input": case.player_input,
        "checks": checks,
        "thoughts_text": thoughts_text,
        "forbidden_hits": {k: v for k, v in forbidden_hits.items() if v},
        "no_forbidden": no_forbidden,
        "word_count": word_count,
        "attempts": attempts,
        "elapsed_s": round(elapsed, 3),
        "narrative_full": narrative,
        "raw_output": raw_output,
        "error": error,
        "all_correct": all(fields) if fields else False,
        "score": round(sum(float(f) for f in fields) / len(fields), 3) if fields else 0.0,
    }


# ============================================================
# Phase 2 state-change scoring
# ============================================================

def _diff_npc_after(diff: Dict[str, Any]) -> Dict[str, str]:
    """Map of NPC key -> after location from the runtime diff."""
    return {
        c.get("npc", ""): c.get("after", "") or ""
        for c in (diff.get("npc_location_changes") or [])
        if c.get("npc")
    }


def _memory_write_targets(phase_two_tool_calls: List[Dict[str, Any]]) -> Set[str]:
    """Set of entity_name arguments from successful write_memory_tool calls."""
    targets: Set[str] = set()
    for c in phase_two_tool_calls:
        if c.get("name") != WRITE_MEMORY_TOOL_NAME:
            continue
        if not _tool_call_succeeded(c):
            continue
        target = (c.get("arguments") or {}).get("entity_name", "") or ""
        if target:
            targets.add(target)
    return targets


def _state_change_breakdown(
    case: PhaseTwoCase,
    before: Dict[str, Any],
    after: Dict[str, Any],
    diff: Dict[str, Any],
    phase_two_tool_calls: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Compare expected state mutations against the actual before/after diff.

    Categories: player_location, npc_locations, quest_flags, visited_locations,
    discovered_locations, memory_writes.

    For each category an expected mutation that occurred is a TP, an expected
    mutation that did not occur is a FN, and an actual mutation that was not
    expected is a FP.
    """
    expected_observed: List[str] = []
    expected_missing: List[str] = []
    unexpected: List[str] = []

    # ---- 1. Player location ----
    before_loc = (before.get("player_location") or "")
    after_loc = (after.get("player_location") or "")
    expected_loc = (case.expected_location_after or "").strip()

    if expected_loc and expected_loc != before_loc:
        # An explicit move is expected.
        label = f"player_location: {before_loc or '(none)'} -> {expected_loc}"
        if after_loc == expected_loc:
            expected_observed.append(label)
        else:
            expected_missing.append(
                f"{label} (actual: {after_loc or '(unchanged)'})"
            )
    elif before_loc != after_loc:
        # The location changed but no change was expected (or expected matches before).
        unexpected.append(f"player_location: {before_loc or '(none)'} -> {after_loc or '(none)'}")

    # ---- 2. NPC locations ----
    actual_npc_after = _diff_npc_after(diff)
    expected_npc = dict(case.expected_npc_locations_after or {})
    before_npc = dict(before.get("npc_locations") or {})

    matched_npcs: Set[str] = set()
    for npc, exp_loc in expected_npc.items():
        prev = before_npc.get(npc, "") or ""
        if exp_loc != prev:
            label = f"npc_location[{npc}]: {prev or '(none)'} -> {exp_loc}"
            if actual_npc_after.get(npc) == exp_loc:
                expected_observed.append(label)
            else:
                actual = actual_npc_after.get(npc) or "(unchanged)"
                expected_missing.append(f"{label} (actual: {actual})")
            matched_npcs.add(npc)

    for change in diff.get("npc_location_changes") or []:
        npc = change.get("npc", "")
        if npc and npc not in matched_npcs:
            unexpected.append(
                f"npc_location[{npc}]: {change.get('before', '') or '(none)'} "
                f"-> {change.get('after', '') or '(none)'}"
            )

    # ---- 3. Quest flags ----
    expected_flags = dict(case.expected_quest_flags_after or {})
    before_flags = dict(before.get("quest_flags") or {})
    after_flags = dict(after.get("quest_flags") or {})

    matched_flags: Set[str] = set()
    for flag, exp_val in expected_flags.items():
        prev = before_flags.get(flag)
        if exp_val != prev:
            label = f"quest_flag[{flag}]: {prev} -> {exp_val}"
            if after_flags.get(flag) == exp_val:
                expected_observed.append(label)
            else:
                expected_missing.append(
                    f"{label} (actual: {after_flags.get(flag)})"
                )
            matched_flags.add(flag)

    for change in diff.get("quest_flag_changes") or []:
        flag = change.get("flag", "")
        if flag and flag not in matched_flags:
            unexpected.append(
                f"quest_flag[{flag}]: {change.get('before')} -> {change.get('after')}"
            )

    # ---- 4. Visited locations ----
    expected_visited = list(case.expected_visited_added or [])
    actual_visited_added = set((diff.get("visited_locations") or {}).get("added") or [])

    matched_visited: Set[str] = set()
    for loc in expected_visited:
        label = f"visited_added: {loc}"
        if loc in actual_visited_added:
            expected_observed.append(label)
        else:
            expected_missing.append(f"{label} (not visited)")
        matched_visited.add(loc)

    for loc in sorted(actual_visited_added):
        if loc not in matched_visited:
            unexpected.append(f"visited_added: {loc}")

    # ---- 5. Discovered locations ----
    expected_discovered = list(case.expected_discovered_added or [])
    actual_discovered_added = set((diff.get("discovered_locations") or {}).get("added") or [])

    matched_discovered: Set[str] = set()
    for loc in expected_discovered:
        label = f"discovered_added: {loc}"
        if loc in actual_discovered_added:
            expected_observed.append(label)
        else:
            expected_missing.append(f"{label} (not discovered)")
        matched_discovered.add(loc)

    for loc in sorted(actual_discovered_added):
        if loc not in matched_discovered:
            unexpected.append(f"discovered_added: {loc}")

    # ---- 6. Memory writes ----
    expected_memory = list(case.expected_memory_writes or [])
    actual_memory_targets = _memory_write_targets(phase_two_tool_calls)

    matched_memory: Set[str] = set()
    for target in expected_memory:
        label = f"memory_write[{target}]"
        if target in actual_memory_targets:
            expected_observed.append(label)
        else:
            expected_missing.append(f"{label} (not written)")
        matched_memory.add(target)

    for target in sorted(actual_memory_targets):
        if target not in matched_memory:
            unexpected.append(f"memory_write[{target}]")

    return {
        "expected_observed": expected_observed,
        "expected_missing": expected_missing,
        "unexpected": unexpected,
        "tp": len(expected_observed),
        "fn": len(expected_missing),
        "fp": len(unexpected),
    }


# ============================================================
# Phase 2 scoring
# ============================================================

def score_phase_two(
    case: PhaseTwoCase,
    finalize_writes_payload: Optional[Dict[str, Any]],
    phase_two_tool_calls: List[Dict[str, Any]],
    location_after: str,
    loop_result: Dict[str, Any],
    elapsed: float,
    iterations: int,
    world_before: Optional[Dict[str, Any]] = None,
    world_after: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    finalize_writes_payload = finalize_writes_payload or {}
    writes_summary = str(finalize_writes_payload.get("writes_summary") or "")
    world_before = world_before or {}
    world_after = world_after or {}

    # Detect "finalize_writes was called" via the tool-call trace.
    finalize_writes_called = any(
        c.get("name") == FINALIZE_WRITES_TOOL_NAME and _tool_call_succeeded(c)
        for c in phase_two_tool_calls
    )

    called_tools = [
        {"name": c.get("name", ""), "arguments": c.get("arguments") or {}}
        for c in phase_two_tool_calls
    ]
    called_names = sorted({c["name"] for c in called_tools if c["name"]})

    # Closed-world function-call breakdown.
    fn_breakdown = _function_call_breakdown(
        case.expected_tools_called,
        called_tools,
        implicit_allowed={FINALIZE_WRITES_TOOL_NAME},
    )
    expected_tools_ok = fn_breakdown["fn"] == 0
    no_unexpected_tools = fn_breakdown["fp"] == 0

    finalize_writes_ok = finalize_writes_called == case.expect_finalize_writes

    location_ok = (
        location_after == case.expected_location_after
        if case.expected_location_after else True
    )

    # State-change breakdown from before/after snapshots.
    diff = diff_runtime_state(world_before, world_after) if world_before and world_after else {}
    state_breakdown = _state_change_breakdown(
        case=case,
        before=world_before,
        after=world_after,
        diff=diff,
        phase_two_tool_calls=phase_two_tool_calls,
    )
    state_changes_ok = state_breakdown["fn"] == 0
    no_unexpected_state_changes = state_breakdown["fp"] == 0

    summary_keywords_ok = (
        _keywords_match(case.expected_writes_summary_keywords, writes_summary)
        if case.expected_writes_summary_keywords else True
    )

    iterations_ok = True
    if case.max_iterations > 0:
        iterations_ok = iterations <= case.max_iterations

    fields: List[bool] = [
        finalize_writes_ok,
        expected_tools_ok,
        no_unexpected_tools,
        location_ok,
        state_changes_ok,
        no_unexpected_state_changes,
    ]
    if case.expected_writes_summary_keywords:
        fields.append(summary_keywords_ok)
    if case.max_iterations > 0:
        fields.append(iterations_ok)

    return {
        "case_id": case.id,
        "case_tags": case.tags,
        "description": case.description,
        "player_input": case.player_input,
        "finalize_writes_called": finalize_writes_called,
        "finalize_writes_ok": finalize_writes_ok,
        "expected_tools": [_format_expected_entry(e) for e in case.expected_tools_called],
        "actual_tools": called_names,
        "expected_tools_ok": expected_tools_ok,
        "no_unexpected_tools": no_unexpected_tools,
        "function_calls": fn_breakdown,
        "expected_location": case.expected_location_after,
        "actual_location": location_after,
        "location_ok": location_ok,
        "state_changes": state_breakdown,
        "state_changes_ok": state_changes_ok,
        "no_unexpected_state_changes": no_unexpected_state_changes,
        "world_before": world_before,
        "world_after": world_after,
        "world_diff": diff,
        "writes_summary": writes_summary,
        "summary_keywords_ok": summary_keywords_ok,
        "expected_summary_keywords": case.expected_writes_summary_keywords,
        "iterations": iterations,
        "iterations_ok": iterations_ok,
        "expected_max_iterations": case.max_iterations,
        "elapsed_s": round(elapsed, 3),
        "loop_status": loop_result.get("status", ""),
        "raw_final": loop_result.get("final_answer", ""),
        "all_rounds": loop_result.get("rounds", []),
        "corrections": _extract_corrections(loop_result.get("rounds", [])),
        "correction_count": len(_extract_corrections(loop_result.get("rounds", []))),
        "tool_trace": phase_two_tool_calls,
        "error": error,
        "all_correct": all(fields),
        "score": round(sum(float(f) for f in fields) / len(fields), 3) if fields else 0.0,
    }


# ============================================================
# Summarisation across cases
# ============================================================

def summarize_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not results:
        return {}

    mean_score = sum(r.get("score", 0) for r in results) / len(results)
    mean_elapsed = sum(r.get("elapsed_s", 0) for r in results) / len(results)

    attempt_values = [r["attempts"] for r in results if r.get("attempts", 0) > 0]
    iteration_values = [r["iterations"] for r in results if r.get("iterations", 0) > 0]
    mean_attempts = sum(attempt_values) / len(attempt_values) if attempt_values else 0.0
    mean_iterations = sum(iteration_values) / len(iteration_values) if iteration_values else 0.0

    tag_scores: Dict[str, List[float]] = {}
    for r in results:
        for tag in r.get("case_tags", []):
            tag_scores.setdefault(tag, []).append(r.get("score", 0))
    tag_summary = {
        tag: round(sum(scores) / len(scores), 3)
        for tag, scores in tag_scores.items()
    }

    failed = [r["case_id"] for r in results if r.get("score", 1) < 0.5]
    perfect = [r["case_id"] for r in results if r.get("all_correct", False)]

    # Aggregate TP/FP/FN across cases for both layers, where present.
    fn_tp = fn_fp = fn_fn = 0
    sc_tp = sc_fp = sc_fn = 0
    fn_cases = sc_cases = 0
    for r in results:
        fc = r.get("function_calls")
        if isinstance(fc, dict):
            fn_tp += int(fc.get("tp", 0))
            fn_fp += int(fc.get("fp", 0))
            fn_fn += int(fc.get("fn", 0))
            fn_cases += 1
        sc = r.get("state_changes")
        if isinstance(sc, dict):
            sc_tp += int(sc.get("tp", 0))
            sc_fp += int(sc.get("fp", 0))
            sc_fn += int(sc.get("fn", 0))
            sc_cases += 1

    out: Dict[str, Any] = {
        "n": len(results),
        "mean_score": round(mean_score, 3),
        "mean_elapsed_s": round(mean_elapsed, 3),
        "mean_attempts": round(mean_attempts, 3),
        "mean_iterations": round(mean_iterations, 3),
        "per_tag": tag_summary,
        "failed_cases": failed,
        "perfect_cases": perfect,
    }
    if fn_cases:
        out["function_calls_totals"] = {"tp": fn_tp, "fp": fn_fp, "fn": fn_fn}
    if sc_cases:
        out["state_changes_totals"] = {"tp": sc_tp, "fp": sc_fp, "fn": sc_fn}
    return out


__all__ = [
    "Timer",
    "score_phase_one",
    "score_narration",
    "score_phase_two",
    "summarize_results",
]
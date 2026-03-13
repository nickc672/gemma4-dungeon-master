from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .test_cases import (
    IntentCase, IntentPhaseCase,
    MechanicsPhaseCase, NarrativeRequirementCase,
)


class Timer:
    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed = time.perf_counter() - self._start



# ============================================================
# Intent Parsing Metrics
# ============================================================

def score_intent(
    case: IntentCase,
    parsed: Dict[str, Any],
    elapsed: float,
    attempts: int,
) -> Dict[str, Any]:

    action_correct = parsed.get("action", "").lower() == case.expected_action.lower()

    parsed_targets = {t.lower().strip() for t in parsed.get("targets", [])}
    expected_targets = {t.lower().strip() for t in case.expected_targets}
    targets_correct = parsed_targets == expected_targets

    fields = [action_correct, targets_correct]

    return {
        "case_id": case.id,
        "case_tags": case.tags,
        "action_correct": action_correct,
        "targets_correct": targets_correct,
        "parsed_targets": sorted(parsed_targets),
        "expected_targets": sorted(expected_targets),
        "attempts": attempts,
        "elapsed_s": round(elapsed, 3),
        "all_correct": all(fields),
        "score": round(sum(float(f) for f in fields) / len(fields), 3),
    }










# ============================================================
# Intent Phase Loop Metrics
# ============================================================

def _normalize_text(text: str) -> str:
    return re.sub(r'[^\w\s]', '', text.lower()).strip()


def _keywords_match(keyword_groups: List[List[str]], actual: str) -> bool:
    #in each group, any single keyword matching is sufficient (OR logic).
    #All groups must match (AND logic).
    
    a = _normalize_text(actual)  # lowercases and strips punctuation
    return all(
        any(kw.lower() in a for kw in group)
        for group in keyword_groups
    )


def _inspection_tool_matches(
    expected: Any,
    called_tools: List[Dict[str, Any]],
) -> bool:

    #inner list = OR group: at least one option must have been called
    if isinstance(expected, list):
        return any(_inspection_tool_matches(option, called_tools) for option in expected)

    if isinstance(expected, str):
        name = expected
        expected_args: Dict[str, Any] = {}
    else:
        name = expected.get("name", "")
        expected_args = expected.get("args") or {}

    for call in called_tools:
        if call.get("name") != name:
            continue
        # now check args if any were specified
        if not expected_args:
            return True
        actual_args = call.get("args") or {}
        if all(actual_args.get(k) == v for k, v in expected_args.items()):
            return True
    return False


def score_intent_phase(
    case: IntentPhaseCase,
    todo_created: bool,
    todo_items: List[Dict[str, Any]],
    summary_text: str,
    tools_called: List[Dict[str, Any]],
    elapsed: float,
    iterations: int,
    rounds: Optional[List[Dict[str, Any]]] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:

    rounds = rounds or []

    #Boolean checks
    todo_created_ok = todo_created == case.expect_todo_created
    summary_ok = bool(summary_text.strip()) == case.expect_summary

    item_count = len(todo_items)
    count_ok = case.min_todo_items <= item_count <= case.max_todo_items

    #Inspection tool checks
    inspection_ok = all(
        _inspection_tool_matches(expected, tools_called)
        for expected in case.expected_inspection_tools
    ) if case.expected_inspection_tools else True

    #called tool names (for reporting)
    called_name_set = {c["name"] for c in tools_called}

    todo_tool_names: set = set()
    for item in todo_items:
        tool_name = str(item.get("tool_name", "")).strip()
        if tool_name:
            todo_tool_names.add(tool_name)

    #Keyword group check
    todo_keywords_ok = True
    if case.expected_todo_keywords:
        todo_keywords_ok = any(
            _keywords_match(case.expected_todo_keywords, item.get("task", ""))
            for item in todo_items
        )

    #Iteration structue checks
    iterations_ok = True
    if case.expected_iterations > 0:
        iterations_ok = iterations == case.expected_iterations

    tool_call_rounds_ok = True
    tool_call_rounds_detail: List[Dict[str, Any]] = []
    if case.expected_tool_call_rounds:
        expected_round_set = set(case.expected_tool_call_rounds)
        for i, rnd in enumerate(rounds):
            had_tool_call = bool(rnd.get("tool_calls"))
            should_have = i in expected_round_set
            tool_call_rounds_detail.append({
                "round": i,
                "had_tool_call": had_tool_call,
                "expected_tool_call": should_have,
                "ok": had_tool_call == should_have,
            })
            if had_tool_call != should_have:
                tool_call_rounds_ok = False

    #Build filds list
    fields: List[bool] = [
        todo_created_ok,
        summary_ok,
        count_ok,
        inspection_ok,
    ]
    if case.expected_todo_keywords:
        fields.append(todo_keywords_ok)
    if case.expected_iterations > 0:
        fields.append(iterations_ok)
    if case.expected_tool_call_rounds:
        fields.append(tool_call_rounds_ok)

    return {
        "case_id": case.id,
        "case_tags": case.tags,
        #Boolean checks
        "todo_created": todo_created,
        "todo_created_ok": todo_created_ok,
        "summary_ok": summary_ok,
        "summary_text": summary_text,
        # Count + tools
        "item_count": item_count,
        "count_ok": count_ok,
        "inspection_ok": inspection_ok,
        "expected_inspection_tools": case.expected_inspection_tools,
        "tools_called": sorted(called_name_set),
        "todo_tool_hints": sorted(todo_tool_names),
        #Keyword check
        "todo_keywords_ok": todo_keywords_ok,
        "expected_todo_keywords": case.expected_todo_keywords,
        #Iteration checks
        "iterations_ok": iterations_ok,
        "expected_iterations": case.expected_iterations,
        "tool_call_rounds_ok": tool_call_rounds_ok,
        "tool_call_rounds_detail": tool_call_rounds_detail,
        "iterations": iterations,
        "elapsed_s": round(elapsed, 3),
        "error": error,
        "all_correct": all(fields),
        "score": round(sum(float(f) for f in fields) / len(fields), 3),
    }










# ============================================================
# Mechanics Phase Metrics
# ============================================================

def score_mechanics_phase(
    case: MechanicsPhaseCase,
    tools_called: List[Dict[str, Any]],
    location_after: str,
    all_resolved: bool,
    has_blocked: bool,
    summary_text: str,
    elapsed: float,
    iterations: int,
    error: Optional[str] = None,
) -> Dict[str, Any]:

    called_set = {c["name"] for c in tools_called}

    tools_correct = all(
        _inspection_tool_matches(expected, tools_called)
        for expected in case.expected_tools_called
    ) if case.expected_tools_called else len(called_set) == 0

    #expected entries to strings for the report renderer.
    def _tool_entry_label(e: Any) -> str:
        if isinstance(e, str):
            return e
        if isinstance(e, dict):
            name = e.get("name", "?")
            args = e.get("args") or {}
            if args:
                arg_str = ", ".join(f"{k}={v}" for k, v in args.items())
                return f"{name}({arg_str})"
            return name
        return str(e)

    expected_tools_labels = [_tool_entry_label(e) for e in case.expected_tools_called]

    forbidden_set = set(case.should_not_call)
    no_forbidden = not bool(called_set & forbidden_set)
    forbidden_violations = sorted(called_set & forbidden_set)

    location_correct = (
        location_after == case.expected_location_after
        if case.expected_location_after
        else True
    )

    resolved_ok = all_resolved == case.expect_all_resolved
    blocked_ok = has_blocked == case.expect_blocked_items
    summary_ok = bool(summary_text.strip()) == case.expect_summary

    fields = [tools_correct, no_forbidden, location_correct, resolved_ok, blocked_ok, summary_ok]

    return {
        "case_id": case.id,
        "case_tags": case.tags,
        "tools_correct": tools_correct,
        "expected_tools": sorted(expected_tools_labels),
        "actual_tools": sorted(called_set),
        "no_forbidden": no_forbidden,
        "forbidden_violations": forbidden_violations,
        "location_correct": location_correct,
        "expected_location": case.expected_location_after,
        "actual_location": location_after,
        "resolved_ok": resolved_ok,
        "all_resolved": all_resolved,
        "blocked_ok": blocked_ok,
        "has_blocked": has_blocked,
        "summary_ok": summary_ok,
        "summary_text": summary_text,
        "iterations": iterations,
        "elapsed_s": round(elapsed, 3),
        "error": error,
        "all_correct": all(fields),
        "score": round(sum(float(f) for f in fields) / len(fields), 3),
    }










# ============================================================
# Narrative Requirement Metrics
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
_SECTION_LABEL = re.compile(r"(?im)^([A-Za-z][A-Za-z _-]*)\s*:")

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


def _extract_section_text(raw: str, section_name: str) -> str:
    #Mirrors the _extract_labeled_block logic used in pipeline.py.
    pattern = re.compile(
        rf"(?im)^{re.escape(section_name)}\s*:\s*(.*?)(?=^\s*[A-Za-z][A-Za-z _-]*\s*:|\Z)",
        re.DOTALL,
    )
    match = pattern.search(raw or "")
    return match.group(1).strip() if match else ""


def _has_section_label(raw: str, section_name: str) -> bool:
    return bool(re.search(rf"(?im)^{re.escape(section_name)}\s*:", raw or ""))


def _section_label_position(raw: str, section_name: str) -> int:
    match = re.search(rf"(?im)^{re.escape(section_name)}\s*:", raw or "")
    return match.start() if match else -1


def _has_bare_first_person_i(text: str) -> bool:
    #Return True if the text contains a standalone "I" that is NOT inside double-quoted speech. 
    stripped = re.sub(r'"[^"]*"', "", text)
    stripped = re.sub(r'\u201c[^\u201d]*\u201d', "", stripped)
    return bool(re.search(r"\bI\b", stripped))


def _build_location_desc_words() -> Dict[str, List[str]]:
    #Load locations.json and extract significant words from each location'sdescription.
    
    import json
    _STOP = {
        "the", "a", "an", "of", "at", "in", "on", "to", "and", "or", "is",
        "it", "its", "as", "by", "for", "from", "with", "that", "this",
        "are", "was", "were", "has", "have", "had", "not", "but", "be",
        "their", "they", "them", "here", "when", "where", "who", "all",
        "one", "two", "into", "out", "up", "no", "more", "than", "so",
        "can", "could", "would", "will", "do", "did", "if", "what", "how",
    }
    _project_root = Path(__file__).resolve().parent.parent
    locations_path = _project_root / "orchestrator" / "world_state" / "data" / "world_model" / "locations.json"
    if not locations_path.exists():
        return {}
    try:
        data = json.loads(locations_path.read_text(encoding="utf-8"))
        result: Dict[str, List[str]] = {}
        for loc in data:
            key = str(loc.get("key", "")).lower()
            desc = str(loc.get("description", ""))
            words = [
                w.strip(".,;:!?\"'()").lower()
                for w in desc.split()
            ]
            significant = list(dict.fromkeys(
                w for w in words if w not in _STOP and len(w) > 3
            ))
            if key and significant:
                result[key] = significant
        return result
    except Exception:
        return {}


_LOCATION_DESC_WORDS: Dict[str, List[str]] = _build_location_desc_words()


def _location_mentioned(location_key: str, text: str) -> bool:
    text_lower = text.lower()
    key_lower = location_key.lower()

    if key_lower in text_lower:
        return True

    _STOP = {"the", "a", "an", "of", "at", "in", "on", "to", "and", "or", "-"}
    words = [
        w for w in re.split(r"[\s\-]+", key_lower)
        if w not in _STOP and len(w) > 2
    ]

    if not words:
        return False

    if any(w in text_lower for w in words):
        return True

    desc_words = _LOCATION_DESC_WORDS.get(key_lower, [])
    if desc_words:
        matched = sum(1 for w in desc_words if w in text_lower)
        return matched >= 2
    return False


def score_narrative_requirement(
    case: NarrativeRequirementCase,
    narrative_text: str,
    current_location: str = "",
    elapsed: float = 0.0,
    attempts: int = 1,
    raw_output: str = "",
) -> Dict[str, Any]:
    
    #Score a single narrative output against the case's check list.
    word_count = len(narrative_text.split())
    thoughts_text = _extract_section_text(raw_output, "Thoughts")

    checks: Dict[str, bool] = {}

    for raw_check in case.checks:
        check, param = _parse_check_param(raw_check, 0)

        #Structural section checks
        if check == "has_two_sections":
            checks[raw_check] = (
                _has_section_label(raw_output, "Thoughts")
                and _has_section_label(raw_output, "Narrative")
            )

        elif check == "thoughts_before_narrative":
            t_pos = _section_label_position(raw_output, "Thoughts")
            n_pos = _section_label_position(raw_output, "Narrative")
            checks[raw_check] = (t_pos >= 0 and n_pos >= 0 and t_pos < n_pos)

        elif check == "thoughts_is_first_person":
            has_i = bool(re.search(r"\bI\b", thoughts_text))
            has_the_player = bool(_THE_PLAYER.search(thoughts_text))
            checks[raw_check] = has_i or has_the_player

        #Narrative content checks (use narrative_text only)
        elif check == "second_person":
            checks[raw_check] = bool(_SECOND_PERSON.search(narrative_text))

        elif check == "no_explicit_choices":
            checks[raw_check] = not bool(_NUMBERED_CHOICES.search(narrative_text))

        elif check == "minimum_length":
            limit = param if param > 0 else _DEFAULT_MINIMUM_LENGTH
            checks[raw_check] = word_count >= limit

        elif check == "concise":
            limit = param if param > 0 else _DEFAULT_CONCISE_MAX
            checks[raw_check] = word_count <= limit

        elif check == "no_player_agency_taken":
            checks[raw_check] = not bool(_AGENCY_TAKEN.search(narrative_text))

        elif check == "narrative_no_the_player":
            checks[raw_check] = not bool(_THE_PLAYER.search(narrative_text))

        elif check == "narrative_no_bare_i":
            checks[raw_check] = not _has_bare_first_person_i(narrative_text)

        elif check == "mentions_current_location":
            if current_location:
                checks[raw_check] = _location_mentioned(current_location, narrative_text)
            else:
                checks[raw_check] = True

        else:
            checks[raw_check] = False

    forbidden_hits: Dict[str, bool] = {}
    for pattern in case.forbidden_patterns:
        forbidden_hits[pattern] = bool(
            re.search(pattern, narrative_text or "", re.IGNORECASE | re.MULTILINE)
        )

    no_forbidden = not any(forbidden_hits.values())

    all_fields: list[bool] = list(checks.values())
    if case.forbidden_patterns:
        all_fields.append(no_forbidden)

    passed = sum(all_fields)
    total = len(all_fields)

    return {
        "case_id": case.id,
        "case_tags": case.tags,
        "checks": checks,
        "thoughts_text": thoughts_text,
        "forbidden_hits": {k: v for k, v in forbidden_hits.items() if v},
        "no_forbidden": no_forbidden,
        "word_count": word_count,
        "attempts": attempts,
        "elapsed_s": round(elapsed, 3),
        "chars_per_second": round(len(narrative_text) / elapsed, 1) if elapsed > 0 else 0,
        "all_correct": passed == total,
        "score": round(passed / total, 3) if total else 0.0,
    }










# ============================================================
# Summary
# ============================================================

def summarize_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not results:
        return {}

    total_score = sum(r.get("score", 0) for r in results)
    mean_score = total_score / len(results)

    total_elapsed = sum(r.get("elapsed_s", 0) for r in results)
    mean_elapsed = total_elapsed / len(results)

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

    return {
        "n": len(results),
        "mean_score": round(mean_score, 3),
        "mean_elapsed_s": round(mean_elapsed, 3),
        "mean_attempts": round(mean_attempts, 3),
        "mean_iterations": round(mean_iterations, 3),
        "per_tag": tag_summary,
        "failed_cases": failed,
        "perfect_cases": perfect,
    }


__all__ = [
    "Timer",
    "score_intent",
    "score_intent_phase",
    "score_mechanics_phase",
    "score_narrative_requirement",
    "summarize_results",
]
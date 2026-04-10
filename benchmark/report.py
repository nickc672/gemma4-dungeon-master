from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _score_color(score: float) -> str:
    if score >= 0.9: return "#2e7d32"
    if score >= 0.7: return "#f57f17"
    if score >= 0.5: return "#e65100"
    return "#c62828"

def _score_bg(score: float) -> str:
    if score >= 0.9: return "#e8f5e9"
    if score >= 0.7: return "#fff8e1"
    if score >= 0.5: return "#fff3e0"
    return "#ffebee"

def _badge(label: str, color: str = "#546e7a") -> str:
    return (f'<span style="display:inline-block;padding:2px 8px;margin:2px;'
            f'border-radius:3px;font-size:0.75em;color:#fff;background:{color};">'
            f'{html.escape(label)}</span>')

def _esc(text: Any) -> str:
    return html.escape(str(text))

def _pass_fail(ok: bool) -> str:
    if ok: return '<span style="color:#2e7d32;font-weight:700;">PASS</span>'
    return '<span style="color:#c62828;font-weight:700;">FAIL</span>'

def _comparison_row(label: str, expected: Any, actual: Any, ok: bool = True) -> str:
    return (f'<tr>'
            f'<td style="padding:4px 12px;font-weight:600;white-space:nowrap;">{_esc(label)}</td>'
            f'<td style="padding:4px 12px;color:#37474f;">{_esc(expected)}</td>'
            f'<td style="padding:4px 12px;color:#37474f;">{_esc(actual)}</td>'
            f'<td style="padding:4px 12px;">{_pass_fail(ok)}</td>'
            f'</tr>')

def _comparison_table(rows_html: str) -> str:
    return ('<table style="width:100%;border-collapse:collapse;font-size:0.85em;margin-top:8px;">'
            '<tr style="background:#eceff1;">'
            '<th style="padding:4px 12px;text-align:left;">Field</th>'
            '<th style="padding:4px 12px;text-align:left;">Expected</th>'
            '<th style="padding:4px 12px;text-align:left;">Actual</th>'
            '<th style="padding:4px 12px;text-align:left;">Result</th>'
            '</tr>' + rows_html + '</table>')

def _raw_block(label: str, text: str) -> str:
    if not text: return ""
    return (f'<div style="margin-top:10px;">'
            f'<div style="font-weight:600;font-size:0.8em;color:#546e7a;margin-bottom:4px;">{_esc(label)}</div>'
            f'<pre style="background:#263238;color:#cfd8dc;padding:12px;border-radius:4px;'
            f'font-size:0.8em;overflow-x:auto;max-height:300px;white-space:pre-wrap;">'
            f'{_esc(text)}</pre></div>')

def _error_block(error: str) -> str:
    if not error: return ""
    return (f'<div style="margin-top:8px;padding:8px 12px;background:#ffebee;border-radius:4px;'
            f'font-size:0.85em;color:#c62828;">'
            f'<strong>Error:</strong> {_esc(error)}</div>')

def _case_dropdown(case_id: str, score: float, title_extra: str, body_html: str) -> str:
    return (f'<details style="margin-bottom:4px;border:1px solid #cfd8dc;border-radius:6px;'
            f'background:{_score_bg(score)};overflow:hidden;">'
            f'<summary style="padding:10px 16px;cursor:pointer;display:flex;'
            f'justify-content:space-between;align-items:center;user-select:none;">'
            f'<span style="font-weight:600;">{_esc(case_id)}'
            f'<span style="font-weight:400;color:#546e7a;margin-left:12px;">{title_extra}</span></span>'
            f'<span style="font-weight:700;color:{_score_color(score)};">{score:.3f}</span>'
            f'</summary>'
            f'<div style="padding:12px 16px;background:#fff;border-top:1px solid #cfd8dc;">'
            f'{body_html}'
            f'</div></details>')

def _pct_bar(score: float, width_px: int = 260) -> str:
    pct = int(score * 100)
    return (f'<div style="display:inline-flex;align-items:center;gap:8px;">'
            f'<div style="width:{width_px}px;background:#e0e0e0;border-radius:4px;height:12px;overflow:hidden;">'
            f'<div style="background:{_score_color(score)};width:{pct}%;height:100%;border-radius:4px;"></div>'
            f'</div>'
            f'<span style="font-weight:700;color:{_score_color(score)};min-width:3em;">{score:.3f}</span>'
            f'</div>')




def _render_round(rnd: dict, is_final: bool = False) -> str:
    """Render a single tool-loop round with full detail: text, tool calls, results, and block reasons."""
    iteration = rnd.get("iteration", "?")
    assistant_text = rnd.get("assistant_text", "")
    tool_calls = rnd.get("tool_calls", [])
    tool_results = rnd.get("tool_results", [])
    hook_notes = rnd.get("hook_notes", [])
    response_block = rnd.get("response_block_reason", "")
    stop_block = rnd.get("stop_block_reason", "")

    if is_final:
        header_color = "#2e7d32"
        header_label = f"Iteration {iteration} - final"
    elif response_block:
        header_color = "#c62828"
        header_label = f"Iteration {iteration} - response blocked"
    elif stop_block:
        header_color = "#e65100"
        header_label = f"Iteration {iteration} - stop hook blocked"
    else:
        header_color = "#546e7a"
        header_label = f"Iteration {iteration}"

    html_parts = [
        f'<div style="margin-bottom:10px;padding:10px 12px;border:1px solid #cfd8dc;'
        f'border-radius:6px;background:#fafafa;">',
        f'<div style="font-weight:700;font-size:0.85em;color:{header_color};margin-bottom:8px;">'
        f'{_esc(header_label)}</div>',
    ]

    #Block reasons shown prominently at the top
    if response_block:
        html_parts.append(
            f'<div style="margin-bottom:6px;padding:6px 10px;background:#ffebee;border-radius:4px;'
            f'font-size:0.82em;color:#c62828;">'
            f'<strong>Response blocked:</strong> {_esc(response_block)}</div>'
        )
    if stop_block:
        html_parts.append(
            f'<div style="margin-bottom:6px;padding:6px 10px;background:#fff3e0;border-radius:4px;'
            f'font-size:0.82em;color:#e65100;">'
            f'<strong>Stop hook:</strong> {_esc(stop_block)}</div>'
        )

    #Assistant text
    if assistant_text:
        html_parts.append(
            f'<div style="font-size:0.78em;font-weight:600;color:#546e7a;margin-bottom:2px;">Assistant</div>'
            f'<pre style="background:#263238;color:#cfd8dc;padding:10px 12px;border-radius:4px;'
            f'font-size:0.79em;overflow-x:auto;max-height:220px;white-space:pre-wrap;margin:0 0 8px 0;">'
            f'{_esc(assistant_text)}</pre>'
        )
    else:
        html_parts.append(
            '<div style="font-size:0.82em;color:#90a4ae;font-style:italic;margin-bottom:6px;">'
            '(no assistant text - tool-only turn)</div>'
        )

    # Tool calls + results
    if tool_calls:
        html_parts.append(
            '<div style="font-size:0.78em;font-weight:600;color:#546e7a;margin-bottom:4px;">Tool Calls</div>'
        )
        result_by_name: dict = {}
        for tr in tool_results:
            result_by_name.setdefault(tr.get("name", ""), []).append(tr.get("result", {}))

        for call in tool_calls:
            call_name = call.get("name", "?")
            call_args = call.get("arguments", {})
            results_for_call = result_by_name.get(call_name, [])
            result_str = json.dumps(results_for_call[0], ensure_ascii=True) if results_for_call else "(no result recorded)"
            succ = results_for_call[0].get("success", results_for_call[0].get("ok", None)) if results_for_call else None
            result_color = "#2e7d32" if succ is True else ("#c62828" if succ is False else "#546e7a")

            html_parts.append(
                f'<div style="margin-bottom:6px;padding:7px 10px;background:#e8f5e9;'
                f'border-left:3px solid #4caf50;border-radius:4px;font-size:0.82em;">'
                f'<span style="font-weight:700;color:#1b5e20;">{_esc(call_name)}</span>'
                f'<span style="color:#546e7a;margin-left:6px;">'
                f'{_esc(json.dumps(call_args, ensure_ascii=True))}</span>'
                f'<div style="color:{result_color};margin-top:3px;">'
                f'&#8627; {_esc(result_str)}</div>'
                f'</div>'
            )
        # Remove used reslts so no double-render
        result_by_name.clear()

    # Hook notes
    if hook_notes:
        for note in hook_notes:
            html_parts.append(
                f'<div style="margin-bottom:4px;padding:4px 8px;background:#fff8e1;border-radius:4px;'
                f'font-size:0.81em;color:#f57f17;">'
                f'<strong>Hook note:</strong> {_esc(str(note))}</div>'
            )

    html_parts.append('</div>')
    return "".join(html_parts)


def _render_earlier_rounds(rounds: list) -> str:
    """Render a collapsed dropdown of all but the last round for tool-loop phases."""
    if len(rounds) <= 1:
        return ""
    earlier = rounds[:-1]
    n = len(earlier)
    blocks = "".join(_render_round(rnd, is_final=False) for rnd in earlier)
    return (
        '<details style="margin-top:8px;">'
        + f'<summary style="cursor:pointer;font-size:0.85em;color:#546e7a;padding:6px 0;">'
        + f'Show {n} earlier iteration(s)</summary>'
        + f'<div style="margin-top:8px;">{blocks}</div>'
        + '</details>'
    )


def _player_input_line(player_input: str) -> str:
    """Render the player input line shown at the top of each case body."""
    if not player_input:
        return ""
    return (
        '<div style="font-size:0.85em;margin-bottom:8px;padding:6px 10px;'
        'background:#e8eaf6;border-radius:4px;color:#263238;">'
        '<strong>Player input:</strong> ' + _esc(player_input) + '</div>'
    )

# ============================================================
# Per-test section renderers
# ============================================================

def _render_intent_results(results: List[Dict]) -> str:
    if not results: return ""
    _avg = sum(r.get("attempts", 1) for r in results) / len(results)
    _avg_bar = (
        '<div style="margin-bottom:16px;padding:10px 16px;background:#eceff1;border-radius:6px;'
        'font-size:0.88em;color:#37474f;">'
        f'<strong>Intent avg attempts:</strong> {_avg:.2f} over {len(results)} cases</div>'
    )
    parts = [_avg_bar]
    for r in results:
        score = r.get("score", 0)
        expected = r.get("expected", {})
        desc = r.get("description", r.get("input", ""))
        title_extra = (f'{_esc(desc)} | '
                       f'Attempts: {r.get("attempts", 1)} | '
                       f'Time: {r.get("elapsed_s", 0):.2f}s')
        parsed_targets = r.get("parsed_targets", [])
        expected_targets = r.get("expected_targets", [])

        rows = _comparison_row("action", expected.get("action", ""),
                               "(correct)" if r.get("action_correct") else "(incorrect -- see raw output)",
                               r.get("action_correct", False))
        rows += _comparison_row("targets",
                                ", ".join(expected_targets) or "(none)",
                                ", ".join(parsed_targets) or "(none)",
                                r.get("targets_correct", False))

        all_raws = r.get("all_attempt_raws", [])
        earlier_attempts_html = ""
        if len(all_raws) > 1:
            earlier_blocks = "".join(
                '<div style="margin-bottom:8px;">'
                + '<div style="font-weight:600;font-size:0.8em;color:#e65100;margin-bottom:4px;">'
                + f'Attempt {i} (failed validation)</div>'
                + _raw_block(f"Raw Output - Attempt {i}", raw)
                + '</div>'
                for i, raw in enumerate(all_raws[:-1], start=1)
            )
            earlier_attempts_html = (
                '<details style="margin-top:8px;">'
                + f'<summary style="cursor:pointer;font-size:0.85em;color:#546e7a;padding:6px 0;">'
                + f'Show {len(all_raws)-1} earlier attempt(s)</summary>'
                + f'<div style="margin-top:8px;">{earlier_blocks}</div>'
                + '</details>'
            )
        body = (f'<div style="font-size:0.85em;color:#546e7a;margin-bottom:8px;">'
                f'Attempts: {r.get("attempts", 1)} | Time: {r.get("elapsed_s", 0):.2f}s</div>'
                + _player_input_line(r.get("player_input", ""))
                + _comparison_table(rows)
                + _error_block(r.get("error", ""))
                + _raw_block("Raw LLM Output", r.get("raw_output", ""))
                + earlier_attempts_html)
        parts.append(_case_dropdown(r.get("case_id", ""), score, title_extra, body))
    return "\n".join(parts)


def _render_corrections(corrections: List[Dict]) -> str:
    if not corrections:
        return ""
    rows = "".join(
        f'<tr>'
        f'<td style="padding:3px 8px;color:#546e7a;">iter {c.get("iteration","?")}</td>'
        f'<td style="padding:3px 8px;color:#c62828;">{_esc(c.get("reason",""))}</td>'
        f'</tr>'
        for c in corrections
    )
    return (
        '<div style="margin-top:10px;">'
        '<div style="font-weight:600;font-size:0.8em;color:#c62828;margin-bottom:4px;">'
        f'Response Hook Corrections ({len(corrections)})</div>'
        '<table style="width:100%;border-collapse:collapse;font-size:0.82em;background:#fff8e1;">'
        '<tr style="background:#fff3e0;">'
        '<th style="padding:3px 8px;text-align:left;">Iteration</th>'
        '<th style="padding:3px 8px;text-align:left;">Correction Issued</th>'
        '</tr>'
        + rows + '</table></div>'
    )


def _render_intent_phase_results(results: List[Dict]) -> str:
    if not results: return ""
    _avg = sum(r.get("iterations", 0) for r in results) / len(results)
    _avg_bar = (
        '<div style="margin-bottom:16px;padding:10px 16px;background:#eceff1;border-radius:6px;'
        'font-size:0.88em;color:#37474f;">'
        f'<strong>Intent phase avg iterations:</strong> {_avg:.2f} over {len(results)} cases</div>'
    )
    parts = [_avg_bar]
    for r in results:
        score = r.get("score", 0)
        correction_count = r.get("correction_count", 0)
        corrections_label = f", corrections={correction_count}" if correction_count else ""
        desc = r.get("description", r.get("player_input", ""))
        title_extra = (f'{_esc(desc)} | '
                       f'Iterations: {r.get("iterations", 0)} | '
                       f'Time: {r.get("elapsed_s", 0):.2f}s | '
                       f'Todo: {r.get("item_count", 0)} items{corrections_label}')

        rows = _comparison_row("todo created", "True", str(r.get("todo_created", False)), r.get("todo_created_ok", False))
        rows += _comparison_row("summary produced", "True", str(bool(r.get("summary_text", "").strip())), r.get("summary_ok", False))
        rows += _comparison_row("todo item count", "in expected range", str(r.get("item_count", 0)), r.get("count_ok", False))

        expected_inspection = r.get("expected_inspection_tools", [])
        tools_called = r.get("tools_called", [])

        def _fmt_inspection(e: Any) -> str:
            if isinstance(e, list):
                return "AnyOf(" + " | ".join(_fmt_inspection(opt) for opt in e) + ")"
            if isinstance(e, str):
                return e
            name = e.get("name", "?")
            args = e.get("args", {})
            if args:
                arg_str = ", ".join(f"{k}={v}" for k, v in args.items())
                return f"{name}({arg_str})"
            return name

        rows += _comparison_row("inspection tools",
                                ", ".join(_fmt_inspection(e) for e in expected_inspection) if expected_inspection else "(no constraint)",
                                ", ".join(tools_called) if tools_called else "(none)",
                                r.get("inspection_ok", False))

        if r.get("expected_todo_keywords"):
            kw_groups = r.get("expected_todo_keywords", [])
            kw_label = " AND ".join("[" + " | ".join(g) + "]" for g in kw_groups)
            rows += _comparison_row(
                "todo keywords",
                kw_label,
                "pass" if r.get("todo_keywords_ok", False) else "fail - no todo item matched all keyword groups",
                r.get("todo_keywords_ok", False),
            )

        if r.get("expected_iterations", 0) > 0:
            rows += _comparison_row(
                "iterations",
                str(r.get("expected_iterations", 0)),
                str(r.get("iterations", 0)),
                r.get("iterations_ok", False),
            )

        if r.get("tool_call_rounds_detail"):
            for rnd_detail in r.get("tool_call_rounds_detail", []):
                rnd_ok = rnd_detail.get("ok", False)
                expected_tc = "tool call" if rnd_detail.get("expected_tool_call") else "no tool call"
                actual_tc = "tool call" if rnd_detail.get("had_tool_call") else "no tool call"
                rows += _comparison_row(
                    f'round {rnd_detail.get("round", "?")} tool call',
                    expected_tc,
                    actual_tc,
                    rnd_ok,
                )

        todo_items = r.get("todo_items", [])
        todo_html = ""
        if todo_items:
            todo_rows = "".join(
                f'<tr><td style="padding:3px 8px;">{i+1}</td>'
                f'<td style="padding:3px 8px;">{_esc(item.get("task",""))}</td>'
                f'<td style="padding:3px 8px;">{_esc(str(item.get("requires_tool",False)))}</td>'
                f'<td style="padding:3px 8px;">{_esc(item.get("status","pending"))}</td></tr>'
                for i, item in enumerate(todo_items)
            )
            todo_html = ('<div style="margin-top:10px;"><div style="font-weight:600;font-size:0.8em;'
                         'color:#546e7a;margin-bottom:4px;">Todo Items Created</div>'
                         '<table style="width:100%;border-collapse:collapse;font-size:0.82em;">'
                         '<tr style="background:#eceff1;">'
                         '<th style="padding:3px 8px;">#</th><th style="padding:3px 8px;">Task</th>'
                         '<th style="padding:3px 8px;">Requires Tool</th>'
                         '<th style="padding:3px 8px;">Status</th></tr>'
                         + todo_rows + '</table></div>')

        summary_text = r.get("summary_text", "")
        summary_html = (f'<div style="margin-top:10px;"><div style="font-weight:600;font-size:0.8em;'
                        f'color:#546e7a;margin-bottom:4px;">Intent Summary</div>'
                        f'<div style="padding:8px 12px;background:#f5f5f5;border-radius:4px;font-size:0.85em;">'
                        f'{_esc(summary_text)}</div></div>') if summary_text else ""

        corrections_html = _render_corrections(r.get("corrections", []))

        earlier_rounds_html = _render_earlier_rounds(r.get("all_rounds", []))
        body = (f'<div style="font-size:0.85em;color:#546e7a;margin-bottom:8px;">'
                f'Iterations: {r.get("iterations",0)} | Corrections: {correction_count} | '
                f'Time: {r.get("elapsed_s",0):.2f}s | Loop status: {r.get("loop_status","")}</div>'
                + _player_input_line(r.get("player_input", ""))
                + _comparison_table(rows) + summary_html + todo_html + corrections_html
                + _error_block(r.get("error","")) + _raw_block("Raw Final LLM Output", r.get("raw_final",""))
                + earlier_rounds_html)
        parts.append(_case_dropdown(r.get("case_id",""), score, title_extra, body))
    return "\n".join(parts)


def _render_mechanics_phase_results(results: List[Dict]) -> str:
    if not results: return ""
    _avg = sum(r.get("iterations", 0) for r in results) / len(results)
    _avg_bar = (
        '<div style="margin-bottom:16px;padding:10px 16px;background:#eceff1;border-radius:6px;'
        'font-size:0.88em;color:#37474f;">'
        f'<strong>Mechanics phase avg iterations:</strong> {_avg:.2f} over {len(results)} cases</div>'
    )
    parts = [_avg_bar]
    for r in results:
        score = r.get("score", 0)
        correction_count = r.get("correction_count", 0)
        corrections_label = f" corrections={correction_count}" if correction_count else ""
        desc = r.get("description", r.get("player_input", ""))
        title_extra = (f'{_esc(desc)} | '
                       f'Iterations: {r.get("iterations", 0)} | '
                       f'Time: {r.get("elapsed_s", 0):.2f}s | '
                       f'Loc: {r.get("actual_location", "?")}{corrections_label}')

        expected_tools = r.get("expected_tools", [])
        actual_tools = r.get("actual_tools", [])
        rows = _comparison_row("tools called",
                               ", ".join(expected_tools) or "(none)",
                               ", ".join(actual_tools) or "(none)",
                               r.get("tools_correct", False))
        violations = r.get("forbidden_violations", [])
        rows += _comparison_row("forbidden tools", "none called",
                                ", ".join(violations) if violations else "none called",
                                r.get("no_forbidden", False))
        rows += _comparison_row("player location", r.get("expected_location",""), r.get("actual_location",""), r.get("location_correct", False))

        all_resolved = r.get("all_resolved", False)
        resolved_ok = r.get("resolved_ok", False)
        expected_resolved = all_resolved if resolved_ok else (not all_resolved)
        rows += _comparison_row("all resolved", "yes" if expected_resolved else "no", "yes" if all_resolved else "no", resolved_ok)

        has_blocked = r.get("has_blocked", False)
        blocked_ok = r.get("blocked_ok", False)
        expected_blocked = has_blocked if blocked_ok else (not has_blocked)
        rows += _comparison_row("has blocked items", "yes" if expected_blocked else "no", "yes" if has_blocked else "no", blocked_ok)
        rows += _comparison_row("summary produced", "True", str(bool(r.get("summary_text","").strip())), r.get("summary_ok", False))

        todo_final = r.get("todo_final", [])
        todo_html = ""
        if todo_final:
            todo_rows = ""
            for i, item in enumerate(todo_final):
                status = item.get("status", "?")
                sc = "#2e7d32" if status == "done" else ("#c62828" if status == "blocked" else "#f57f17")
                todo_rows += (f'<tr><td style="padding:3px 8px;">{i+1}</td>'
                              f'<td style="padding:3px 8px;">{_esc(item.get("task",""))}</td>'
                              f'<td style="padding:3px 8px;color:{sc};font-weight:600;">{_esc(status)}</td>'
                              f'<td style="padding:3px 8px;">{_esc(str(item.get("used_tool",False)))}</td>'
                              f'<td style="padding:3px 8px;font-size:0.9em;">{_esc(item.get("resolution",""))}</td></tr>')
            counts = r.get("todo_counts", {})
            count_str = ", ".join(f'{k}={v}' for k, v in counts.items())
            todo_html = (f'<div style="margin-top:10px;"><div style="font-weight:600;font-size:0.8em;'
                         f'color:#546e7a;margin-bottom:4px;">Todo Final State ({count_str})</div>'
                         '<table style="width:100%;border-collapse:collapse;font-size:0.82em;">'
                         '<tr style="background:#eceff1;">'
                         '<th style="padding:3px 8px;">#</th><th style="padding:3px 8px;">Task</th>'
                         '<th style="padding:3px 8px;">Status</th><th style="padding:3px 8px;">Used Tool</th>'
                         '<th style="padding:3px 8px;">Resolution</th></tr>'
                         + todo_rows + '</table></div>')

        trace = r.get("world_tool_trace", [])
        trace_html = ""
        if trace:
            tp = []
            for i, call in enumerate(trace):
                res = call.get("result", {})
                succ = res.get("success", res.get("ok", None))
                ss = ' style="color:#2e7d32;"' if succ is True else (' style="color:#c62828;"' if succ is False else "")
                tp.append(f'<div style="margin-bottom:6px;padding:6px 8px;background:#f5f5f5;border-radius:4px;font-size:0.82em;">'
                           f'<span style="font-weight:600;">{i+1}. {_esc(call.get("name",""))}</span>'
                           f'(<span style="color:#546e7a;">{_esc(json.dumps(call.get("arguments",{})))}</span>)'
                           f'<div{ss}>Result: {_esc(json.dumps(res))}</div></div>')
            trace_html = ('<div style="margin-top:10px;"><div style="font-weight:600;font-size:0.8em;'
                          'color:#546e7a;margin-bottom:4px;">World Tool Trace</div>'
                          + "".join(tp) + '</div>')

        summary_text = r.get("summary_text", "")
        summary_html = (f'<div style="margin-top:10px;"><div style="font-weight:600;font-size:0.8em;'
                        f'color:#546e7a;margin-bottom:4px;">Mechanics Summary</div>'
                        f'<div style="padding:8px 12px;background:#f5f5f5;border-radius:4px;font-size:0.85em;">'
                        f'{_esc(summary_text)}</div></div>') if summary_text else ""

        corrections_html = _render_corrections(r.get("corrections", []))

        earlier_rounds_html = _render_earlier_rounds(r.get("all_rounds", []))
        body = (f'<div style="font-size:0.85em;color:#546e7a;margin-bottom:8px;">'
                f'Iterations: {r.get("iterations",0)} | Corrections: {correction_count} | '
                f'Time: {r.get("elapsed_s",0):.2f}s | Loop status: {r.get("loop_status","")}</div>'
                + _player_input_line(r.get("player_input", ""))
                + _comparison_table(rows) + summary_html + todo_html + trace_html + corrections_html
                + _error_block(r.get("error","")) + _raw_block("Raw Final LLM Output", r.get("raw_final",""))
                + earlier_rounds_html)
        parts.append(_case_dropdown(r.get("case_id",""), score, title_extra, body))
    return "\n".join(parts)


def _render_narrative_results(results: List[Dict]) -> str:
    if not results: return ""

    # Narrative-specific average attempt count
    attempt_vals = [r.get("attempts", 1) for r in results]
    avg_attempts = sum(attempt_vals) / len(attempt_vals) if attempt_vals else 0
    avg_attempts_html = (
        f'<div style="margin-bottom:16px;padding:10px 16px;background:#eceff1;border-radius:6px;'
        f'font-size:0.88em;color:#37474f;">'
        f'<strong>Narrative avg attempts:</strong> {avg_attempts:.2f} over {len(results)} cases</div>'
    )

    parts = [avg_attempts_html]
    for r in results:
        score = r.get("score", 0)
        attempts = r.get("attempts", 1)
        elapsed = r.get("elapsed_s", 0)
        word_count = r.get("word_count", 0)
        desc = r.get("description", "")
        title_extra = (f'{_esc(desc)} | '
                       f'Attempts: {attempts} | '
                       f'Time: {elapsed:.2f}s | '
                       f'Words: {word_count}')

        checks = r.get("checks", {})
        rows = ""
        for check_name, passed in checks.items():
            rows += _comparison_row(check_name, "pass", "pass" if passed else "fail", passed)
        for section, found in r.get("section_hits", {}).items():
            rows += _comparison_row(f'section: {section}', "present", "present" if found else "missing", found)
        for pattern, hit in r.get("forbidden_hits", {}).items():
            rows += _comparison_row(f'forbidden: {pattern}', "not present", "FOUND" if hit else "not present", not hit)

        #Last attept output (shown by default)
        narrative = r.get("narrative_full", "")
        narrative_html = (
            f'<div style="margin-top:10px;">'
            f'<div style="font-weight:600;font-size:0.8em;color:#546e7a;margin-bottom:4px;">Generated Narrative</div>'
            f'<div style="padding:12px;background:#f5f5f5;border-radius:4px;font-size:0.85em;'
            f'font-style:italic;color:#37474f;max-height:300px;overflow-y:auto;">'
            f'{_esc(narrative)}</div></div>'
        ) if narrative else ""

        raw_output = r.get("raw_output", "")
        last_attempt_html = _raw_block("Raw LLM Output (last attempt)", raw_output)

        #Earlier attempts dropdown (only if there were retries)
        all_raws = r.get("all_attempt_raws", [])
        earlier_attempts_html = ""
        if len(all_raws) > 1:
            earlier_blocks = ""
            for i, raw in enumerate(all_raws[:-1], start=1):
                earlier_blocks += (
                    f'<div style="margin-bottom:8px;">'
                    f'<div style="font-weight:600;font-size:0.8em;color:#e65100;margin-bottom:4px;">'
                    f'Attempt {i} (failed validation)</div>'
                    + _raw_block(f"Raw Output - Attempt {i}", raw)
                    + '</div>'
                )
            earlier_attempts_html = (
                f'<details style="margin-top:8px;">'
                f'<summary style="cursor:pointer;font-size:0.85em;color:#546e7a;padding:6px 0;">'
                f'Show {len(all_raws) - 1} earlier attempt(s)</summary>'
                f'<div style="margin-top:8px;">{earlier_blocks}</div>'
                f'</details>'
            )

        body = (
            f'<div style="font-size:0.85em;color:#546e7a;margin-bottom:8px;">'
            f'Attempts: {attempts} | Time: {elapsed:.2f}s | Words: {word_count}</div>'
            + _player_input_line(r.get("player_input", ""))
            + _comparison_table(rows)
            + narrative_html
            + _error_block(r.get("error", ""))
            + last_attempt_html
            + earlier_attempts_html
        )
        parts.append(_case_dropdown(r.get("case_id", ""), score, title_extra, body))
    return "\n".join(parts)


# ============================================================
# Per-model summary card
# ============================================================

def _render_summary_card(model: str, data: Dict[str, Any]) -> str:
    overall = data.get("overall", {})
    score = overall.get("mean_score", 0)
    elapsed = data.get("total_elapsed_s", 0)
    timestamp = data.get("timestamp", "")
    mean_attempts = overall.get("mean_attempts", 0)
    mean_iterations = overall.get("mean_iterations", 0)

    tests_data = data.get("tests", {})
    test_bars = []
    for test_name in ["intent", "intent_phase", "mechanics_phase", "narrative"]:
        t = tests_data.get(test_name)
        if t is None: continue
        s = t.get("summary", {})
        t_score = s.get("mean_score", 0)
        n = s.get("n", 0)
        pct = int(t_score * 100)
        test_bars.append(
            f'<div style="margin-bottom:6px;">'
            f'<div style="display:flex;justify-content:space-between;font-size:0.85em;margin-bottom:2px;">'
            f'<span>{_esc(test_name)}</span><span>{t_score:.3f} ({n} cases)</span></div>'
            f'<div style="background:#e0e0e0;border-radius:4px;height:14px;overflow:hidden;">'
            f'<div style="background:{_score_color(t_score)};width:{pct}%;height:100%;border-radius:4px;"></div>'
            f'</div></div>'
        )

    failed = overall.get("failed_cases", [])
    failed_html = (f'<div style="margin-top:12px;padding:8px 12px;background:#ffebee;border-radius:4px;'
                   f'font-size:0.85em;color:#c62828;">'
                   f'<strong>Failed cases:</strong> {_esc(", ".join(failed))}</div>') if failed else ""

    return (f'<div style="background:#fff;border:1px solid #cfd8dc;border-radius:8px;padding:24px;margin-bottom:24px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:16px;">'
            f'<h2 style="margin:0;color:#263238;">{_esc(model)}</h2>'
            f'<span style="font-size:0.85em;color:#78909c;">{_esc(timestamp)}</span></div>'
            f'<div style="display:flex;gap:32px;margin-bottom:16px;">'
            f'<div><div style="font-size:0.8em;color:#78909c;text-transform:uppercase;">Overall</div>'
            f'<div style="font-size:2em;font-weight:700;color:{_score_color(score)};">{score:.3f}</div></div>'
            f'<div><div style="font-size:0.8em;color:#78909c;text-transform:uppercase;">Total Time</div>'
            f'<div style="font-size:2em;font-weight:700;color:#37474f;">{elapsed:.1f}s</div></div>'
            f'<div><div style="font-size:0.8em;color:#78909c;text-transform:uppercase;">Avg Attempts</div>'
            f'<div style="font-size:2em;font-weight:700;color:#37474f;">{mean_attempts:.2f}</div></div>'
            f'<div><div style="font-size:0.8em;color:#78909c;text-transform:uppercase;">Avg Iterations</div>'
            f'<div style="font-size:2em;font-weight:700;color:#37474f;">{mean_iterations:.2f}</div></div>'
            f'</div>'
            f'<div style="max-width:500px;">{"".join(test_bars)}</div>'
            f'{failed_html}</div>')


def _render_tag_table(overall: Dict[str, Any]) -> str:
    per_tag = overall.get("per_tag", {})
    if not per_tag: return ""
    rows = []
    for tag in sorted(per_tag.keys()):
        ts = per_tag[tag]
        rows.append(f'<tr>'
                    f'<td style="padding:4px 12px;">{_badge(tag, _score_color(ts))}</td>'
                    f'<td style="padding:4px 12px;font-weight:600;color:{_score_color(ts)};">{ts:.3f}</td>'
                    f'</tr>')
    return ('<div style="margin-bottom:24px;"><h3 style="color:#263238;">Score by Tag</h3>'
            '<table style="border-collapse:collapse;">' + "\n".join(rows) + '</table></div>')


# ============================================================
# Single-model tab panel HTML
# ============================================================

_SECTION_RENDERERS = {
    "intent":          ("Intent Parsing",            _render_intent_results),
    "intent_phase":    ("Intent Phase (Agent Loop)", _render_intent_phase_results),
    "mechanics_phase": ("Mechanics Phase (Agent Loop)", _render_mechanics_phase_results),
    "narrative":       ("Narrative Requirement",         _render_narrative_results),
}


def _render_model_panel(model: str, data: Dict[str, Any]) -> str:
    if "error" in data:
        return (f'<div style="background:#ffebee;padding:16px;border-radius:8px;margin-bottom:24px;">'
                f'<h2 style="color:#c62828;">{_esc(model)} - ERROR</h2>'
                f'<pre>{_esc(data["error"])}</pre></div>')

    sections = [_render_summary_card(model, data), _render_tag_table(data.get("overall", {}))]
    tests = data.get("tests", {})
    for test_name in ["intent", "intent_phase", "mechanics_phase", "narrative"]:
        test_data = tests.get(test_name)
        if test_data is None: continue
        title, renderer = _SECTION_RENDERERS.get(test_name, (test_name, None))
        if renderer is None: continue
        summary = test_data.get("summary", {})
        s_score = summary.get("mean_score", 0)
        n = summary.get("n", 0)
        sections.append(
            f'<div style="margin-bottom:32px;">'
            f'<h3 style="color:#263238;border-bottom:2px solid #cfd8dc;padding-bottom:8px;">'
            f'{_esc(title)}'
            f'<span style="font-size:0.7em;font-weight:400;color:{_score_color(s_score)};margin-left:12px;">'
            f'{s_score:.3f} ({n} cases)</span></h3>'
            + renderer(test_data.get("results", []))
            + '</div>'
        )
    return "\n".join(sections)


# ============================================================
# Compare tab
# ============================================================

def _render_compare_panel(all_data: Dict[str, Dict[str, Any]]) -> str:
    models = [m for m, d in all_data.items() if "error" not in d]
    if not models:
        return '<p style="color:#c62828;">No successful model runs to compare.</p>'

    COLORS = ["#1565c0","#6a1b9a","#00695c","#e65100","#558b2f","#ad1457","#0277bd"]
    def mc(i): return COLORS[i % len(COLORS)]

    # 1. Leaderboard
    ranked = sorted(models, key=lambda m: all_data[m].get("overall", {}).get("mean_score", 0), reverse=True)
    leaderboard_rows = ""
    for rank, model in enumerate(ranked, 1):
        d = all_data[model]
        overall = d.get("overall", {})
        score = overall.get("mean_score", 0)
        elapsed = d.get("total_elapsed_s", 0)
        n = overall.get("n", 0)
        medal = {1: "1st", 2: "2nd", 3: "3rd"}.get(rank, f"#{rank}")
        leaderboard_rows += (
            f'<tr style="background:{_score_bg(score)};">'
            f'<td style="padding:8px 16px;font-size:1.1em;">{medal}</td>'
            f'<td style="padding:8px 16px;font-weight:700;">{_esc(model)}</td>'
            f'<td style="padding:8px 16px;">{_pct_bar(score, 220)}</td>'
            f'<td style="padding:8px 16px;color:#546e7a;">{elapsed:.1f}s total, {n} cases</td>'
            f'</tr>'
        )
    leaderboard_html = (
        '<div style="margin-bottom:32px;">'
        '<h3 style="color:#263238;border-bottom:2px solid #cfd8dc;padding-bottom:8px;">Leaderboard</h3>'
        '<table style="width:100%;border-collapse:collapse;font-size:0.9em;">'
        + leaderboard_rows + '</table></div>'
    )

    # 2. Per-test score comparison
    test_names = ["intent", "intent_phase", "mechanics_phase", "narrative"]
    test_labels = {"intent": "Intent Parsing", "intent_phase": "Intent Phase",
                   "mechanics_phase": "Mechanics Phase", "narrative": "Narrative Requirement"}
    test_section_rows = ""
    for test in test_names:
        row_cells = f'<td style="padding:6px 12px;font-weight:600;">{test_labels[test]}</td>'
        for i, model in enumerate(ranked):
            score = all_data[model].get("tests", {}).get(test, {}).get("summary", {}).get("mean_score", None)
            if score is None:
                row_cells += '<td style="padding:6px 12px;color:#9e9e9e;">n/a</td>'
            else:
                row_cells += f'<td style="padding:6px 12px;">{_pct_bar(score, 180)}</td>'
        test_section_rows += f'<tr>{row_cells}</tr>'
    model_headers = "".join(
        f'<th style="padding:6px 12px;text-align:left;color:{mc(i)};">{_esc(m)}</th>'
        for i, m in enumerate(ranked)
    )
    test_compare_html = (
        '<div style="margin-bottom:32px;">'
        '<h3 style="color:#263238;border-bottom:2px solid #cfd8dc;padding-bottom:8px;">Test Scores</h3>'
        '<table style="width:100%;border-collapse:collapse;font-size:0.88em;">'
        f'<tr style="background:#eceff1;"><th style="padding:6px 12px;text-align:left;">Test</th>'
        + model_headers + '</tr>' + test_section_rows + '</table></div>'
    )

    # 3. Tag comparison
    all_tags: set = set()
    for model in models:
        all_tags.update(all_data[model].get("overall", {}).get("per_tag", {}).keys())
    tag_rows = ""
    for tag in sorted(all_tags):
        tag_cells = f'<td style="padding:5px 12px;">{_badge(tag)}</td>'
        for model in ranked:
            tag_score = all_data[model].get("overall", {}).get("per_tag", {}).get(tag)
            if tag_score is None:
                tag_cells += '<td style="padding:5px 12px;color:#9e9e9e;">n/a</td>'
            else:
                tag_cells += f'<td style="padding:5px 12px;font-weight:600;color:{_score_color(tag_score)};">{tag_score:.3f}</td>'
        tag_rows += f'<tr>{tag_cells}</tr>'
    tag_compare_html = ""
    if tag_rows:
        tag_model_headers = "".join(
            f'<th style="padding:5px 12px;text-align:left;color:{mc(i)};">{_esc(m)}</th>'
            for i, m in enumerate(ranked)
        )
        tag_compare_html = (
            '<div style="margin-bottom:32px;">'
            '<h3 style="color:#263238;border-bottom:2px solid #cfd8dc;padding-bottom:8px;">Score by Tag</h3>'
            '<table style="border-collapse:collapse;font-size:0.88em;">'
            f'<tr style="background:#eceff1;"><th style="padding:5px 12px;text-align:left;">Tag</th>'
            + tag_model_headers + '</tr>' + tag_rows + '</table></div>'
        )

    # 4. Case-by-case breakdown
    case_scores: Dict[str, Dict[str, Optional[float]]] = {}
    for model in models:
        for test_key in test_names:
            for r in all_data[model].get("tests", {}).get(test_key, {}).get("results", []):
                cid = r.get("case_id", "?")
                if cid not in case_scores:
                    case_scores[cid] = {m: None for m in ranked}
                case_scores[cid][model] = r.get("score")
    case_rows = ""
    for cid in sorted(case_scores.keys()):
        scores_for_case = case_scores[cid]
        cells = f'<td style="padding:4px 10px;font-weight:600;font-size:0.88em;">{_esc(cid)}</td>'
        for model in ranked:
            s = scores_for_case.get(model)
            if s is None:
                cells += '<td style="padding:4px 10px;text-align:center;color:#9e9e9e;">n/a</td>'
            else:
                bg = _score_bg(s)
                fc = _score_color(s)
                mark = "pass" if s >= 1.0 else ("partial" if s >= 0.5 else "fail")
                cells += (f'<td style="padding:4px 10px;text-align:center;background:{bg};'
                          f'font-weight:700;color:{fc};">{s:.2f} {mark}</td>')
        case_rows += f'<tr>{cells}</tr>'
    case_model_headers = "".join(
        f'<th style="padding:4px 10px;text-align:center;color:{mc(i)};">{_esc(m)}</th>'
        for i, m in enumerate(ranked)
    )
    case_compare_html = (
        '<div style="margin-bottom:32px;">'
        '<h3 style="color:#263238;border-bottom:2px solid #cfd8dc;padding-bottom:8px;">Case-by-Case Breakdown</h3>'
        '<p style="font-size:0.85em;color:#546e7a;margin-top:-4px;">pass = perfect &nbsp; partial = partial credit &nbsp; fail = failed</p>'
        '<div style="overflow-x:auto;">'
        '<table style="border-collapse:collapse;font-size:0.85em;min-width:100%;">'
        f'<tr style="background:#eceff1;"><th style="padding:4px 10px;text-align:left;">Case</th>'
        + case_model_headers + '</tr>' + case_rows + '</table></div></div>'
    )

    # 5. Performance table
    perf_rows = ""
    metrics = [
        ("Mean Score",        lambda d: d.get("overall", {}).get("mean_score", 0),         ".3f", True),
        ("Total Time (s)",    lambda d: d.get("total_elapsed_s", 0),                        ".1f", False),
        ("Avg Time/Case (s)", lambda d: d.get("overall", {}).get("mean_elapsed_s", 0),      ".2f", False),
        ("Avg Attempts",      lambda d: d.get("overall", {}).get("mean_attempts", 0),       ".2f", False),
        ("Avg Iterations",    lambda d: d.get("overall", {}).get("mean_iterations", 0),     ".2f", False),
        ("Perfect Cases",     lambda d: len(d.get("overall", {}).get("perfect_cases", [])), "d",   True),
        ("Failed Cases",      lambda d: len(d.get("overall", {}).get("failed_cases", [])),  "d",   False),
    ]
    for label, fn, fmt, higher_better in metrics:
        vals = [(m, fn(all_data[m])) for m in ranked]
        best_val = max(v for _, v in vals) if higher_better else min(v for _, v in vals)
        cells = f'<td style="padding:5px 12px;font-weight:600;">{_esc(label)}</td>'
        for model, val in vals:
            is_best = (val == best_val)
            bold = "font-weight:700;" if is_best else ""
            bg = "background:#e8f5e9;" if is_best else ""
            formatted = f"{val:{fmt}}"
            cells += f'<td style="padding:5px 12px;{bold}{bg}text-align:center;">{formatted}</td>'
        perf_rows += f'<tr>{cells}</tr>'
    perf_model_headers = "".join(
        f'<th style="padding:5px 12px;text-align:center;color:{mc(i)};">{_esc(m)}</th>'
        for i, m in enumerate(ranked)
    )
    perf_html = (
        '<div style="margin-bottom:32px;">'
        '<h3 style="color:#263238;border-bottom:2px solid #cfd8dc;padding-bottom:8px;">Performance and Efficiency</h3>'
        '<p style="font-size:0.85em;color:#546e7a;margin-top:-4px;">Highlighted cell = best value for that metric.</p>'
        '<table style="border-collapse:collapse;font-size:0.88em;">'
        f'<tr style="background:#eceff1;"><th style="padding:5px 12px;text-align:left;">Metric</th>'
        + perf_model_headers + '</tr>' + perf_rows + '</table></div>'
    )

    return leaderboard_html + test_compare_html + tag_compare_html + case_compare_html + perf_html


# ============================================================
# Mainfunction
# ============================================================

def generate_report(all_data: Dict[str, Dict[str, Any]], output_path: str) -> None:
    models = list(all_data.keys())
    multi = len(models) > 1

    tab_ids = [f"model-{i}" for i in range(len(models))]
    if multi:
        tab_ids.append("compare")

    tab_bar = ""
    if multi:
        tab_buttons = []
        for i, model in enumerate(models):
            active = ' class="tab-btn active"' if i == 0 else ' class="tab-btn"'
            tab_buttons.append(f'<button{active} onclick="showTab(\'model-{i}\')">{_esc(model)}</button>')
        tab_buttons.append('<button class="tab-btn" onclick="showTab(\'compare\')">Compare</button>')
        tab_bar = '<div class="tab-bar">' + "\n".join(tab_buttons) + "</div>\n"

    panel_html_parts = []
    for i, (model, data) in enumerate(all_data.items()):
        tab_id = f"model-{i}"
        display = "block" if i == 0 else "none"
        panel_html_parts.append(
            f'<div id="panel-{tab_id}" class="tab-panel" style="display:{display};">'
            + _render_model_panel(model, data)
            + '</div>'
        )

    if multi:
        panel_html_parts.append(
            '<div id="panel-compare" class="tab-panel" style="display:none;">'
            + _render_compare_panel(all_data)
            + '</div>'
        )

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DM Pipeline Benchmark Report</title>
<style>
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  max-width: 1200px; margin: 0 auto; padding: 24px;
  background: #eceff1; color: #263238;
}}
h1 {{ color: #263238; margin-bottom: 4px; }}
h3 {{ color: #263238; }}
table {{ font-size: 0.9em; }}
th {{ text-align: left; }}
details summary {{ list-style: none; }}
details summary::-webkit-details-marker {{ display: none; }}
details summary::before {{ content: "\\25B6  "; font-size: 0.7em; transition: transform 0.2s; display: inline-block; }}
details[open] summary::before {{ transform: rotate(90deg); }}
details summary:hover {{ filter: brightness(0.97); }}
.tab-bar {{
  display: flex; flex-wrap: wrap; gap: 4px;
  margin-bottom: 24px; border-bottom: 2px solid #b0bec5; padding-bottom: 0;
}}
.tab-btn {{
  padding: 8px 18px; border: 1px solid #b0bec5; border-bottom: none;
  border-radius: 6px 6px 0 0; background: #eceff1; color: #546e7a;
  cursor: pointer; font-size: 0.9em; font-weight: 600;
  transition: background 0.15s;
}}
.tab-btn:hover {{ background: #cfd8dc; }}
.tab-btn.active {{
  background: #fff; color: #263238;
  border-color: #b0bec5; border-bottom: 2px solid #fff;
  margin-bottom: -2px;
}}
</style>
</head><body>
<h1>DM Pipeline Benchmark Report</h1>
<p style="color:#78909c;margin-bottom:{'8px' if multi else '24px'};">
  Pipeline: intent parse - intent agent phase - mechanics agent phase - narrate
  {'&nbsp;|&nbsp; <strong>' + str(len(models)) + ' models compared</strong>' if multi else ''}
</p>
{tab_bar}
{''.join(panel_html_parts)}
<script>
function showTab(tabId) {{
  document.querySelectorAll('.tab-panel').forEach(p => p.style.display = 'none');
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  var panel = document.getElementById('panel-' + tabId);
  if (panel) panel.style.display = 'block';
  var btn = document.querySelector('[onclick="showTab(\\''+tabId+'\\')"]');
  if (btn) btn.classList.add('active');
}}
</script>
</body></html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(page)


# ============================================================
# JSON loader
# ============================================================

def load_results_from_json(path: Path) -> Dict[str, Dict[str, Any]]:
    """
    Load a per-model results JSON file.

    Each file is written by runner.py as:
        { "model-name": { ...result dict... } }

    Returns the same dict shape that generate_report expects:
        { "model-name": { ...result dict... }, ... }
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object at the top level")

    #each key should be a model name maping to its result dict.
    out: Dict[str, Dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            raise ValueError(f"{path}: value for key '{key}' is not an object")
        out[key] = value
    return out


# ============================================================
# CLI entry point
# ============================================================

def _find_latest_result_files(n: int) -> List[Path]:
    """Return the N most recently modified *_results.json files from benchmark/output/."""
    output_dir = Path(__file__).resolve().parent / "output"
    if not output_dir.exists():
        return []
    candidates = sorted(
        output_dir.glob("*_results.json"),
        key=lambda p: p.stat().st_mtime,
    )
    return candidates[-n:]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Combine one or more per-model JSON result files into a comparison HTML report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Auto-pick the 3 most recent result files\n"
            "  python3 -m benchmark.report --latest 3\n\n"
            "  # Compare two explicit files\n"
            "  python3 -m benchmark.report output/ts_modelA_results.json output/ts_modelB_results.json\n\n"
            "  # Custom output path\n"
            "  python3 -m benchmark.report --latest 2 --output my_comparison.html\n"
        ),
    )
    parser.add_argument(
        "json_files", nargs="*", metavar="RESULTS_JSON",
        help="Per-model JSON files produced by benchmark.runner (omit if using --latest)",
    )
    parser.add_argument(
        "--latest", "-n", type=int, default=None, metavar="N",
        help="Pick the N most recently modified *_results.json files from benchmark/output/",
    )
    parser.add_argument(
        "--output", "-o", default="",
        help=(
            "Path for the HTML report. "
            "Defaults to benchmark/output/<timestamp>_comparison_report.html"
        ),
    )
    args = parser.parse_args()

    #Resolve file list
    if args.latest is not None:
        if args.json_files:
            print("[ERROR] Cannot combine --latest with explicit file paths.", file=sys.stderr)
            sys.exit(1)
        resolved_files = _find_latest_result_files(args.latest)
        if not resolved_files:
            print("[ERROR] No *_results.json files found in benchmark/output/", file=sys.stderr)
            sys.exit(1)
        if len(resolved_files) < args.latest:
            print(f"[WARNING] Only {len(resolved_files)} result file(s) found, requested {args.latest}.")
        print(f"Using {len(resolved_files)} most recent result file(s):")
        for p in resolved_files:
            print(f"  {p.name}")
        print()
    else:
        if not args.json_files:
            parser.print_help()
            sys.exit(1)
        resolved_files = [Path(p).expanduser().resolve() for p in args.json_files]

    # Load all JSON files
    all_data: Dict[str, Dict[str, Any]] = {}
    for path in resolved_files:
        if not path.exists():
            print(f"[ERROR] File not found: {path}", file=sys.stderr)
            sys.exit(1)
        try:
            file_data = load_results_from_json(path)
        except Exception as exc:
            print(f"[ERROR] Could not load {path}: {exc}", file=sys.stderr)
            sys.exit(1)

        for model_name, result in file_data.items():
            if model_name in all_data:
                model_name = f"{model_name} ({path.stem})"
            all_data[model_name] = result
        print(f"Loaded: {path.name}  -->  {', '.join(file_data.keys())}")

    if not all_data:
        print("[ERROR] No results loaded.", file=sys.stderr)
        sys.exit(1)

    # output path
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        output_dir = Path(__file__).resolve().parent / "output"
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"{timestamp}_comparison_report.html"

    generate_report(all_data, str(output_path))
    print(f"\nReport written to: {output_path}")


if __name__ == "__main__":
    main()
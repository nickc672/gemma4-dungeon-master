from __future__ import annotations
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from orchestrator.runtime_flow.pipeline import StoryEngine
from orchestrator.runtime_flow.turn_context import TurnContext
from orchestrator.runtime_flow.reconciliation import build_runtime_state_snapshot
from orchestrator.runtime_flow.phases import PhaseOneInput, NarrationInput, PhaseTwoInput
from orchestrator.world_state.story import mark_location_visited
from orchestrator.world_state.tools import bind_turn_orchestration_ctx, clear_turn_orchestration_ctx
from .scenarios import PhaseOneCase, PHASE_ONE_CASES, NarrationCase, NARRATION_CASES, PhaseTwoCase, PHASE_TWO_CASES,
from .metrics import Timer, score_phase_one, score_narration, score_phase_two, summarize_results
# Make the orchestrator package importable when running as `python -m benchmark.runner`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


"""
Benchmark runner for the orchestrator pipeline.

For each phase (Phase 1, Narration, Phase 2), the runner:
  1. Builds a fresh StoryEngine with the target model.
  2. Configures the engine's game_state to match the scenario.
  3. Builds the typed input the phase runner expects.
  4. Calls engine.phase_<n>.run(input) and times it.
  5. Scores the typed output.
  6. Saves a JSON result file (one per model run).

Anything inside the orchestrator package can be reorganised without
affecting this file as long as the public APIs hold: StoryEngine,
engine.phase_one/narration/phase_two, the input/output dataclasses,
TurnContext, and the bind/clear helpers.
"""



# ============================================================
# Engine construction and per-case state configuration
# ============================================================
DEFAULT_ROLL_PRESET = 10

def _preset_roll_provider(roll_value: int) -> Callable[[Dict[str, Any]], int]:
    """
    Build a non-interactive d20 roll provider that always returns a fixed value.
    Used by the benchmark for cases that trigger a skill_check
    """
    clamped = max(1, min(20, int(roll_value)))

    def provider(request: Dict[str, Any]) -> int:
        _ = request
        return clamped

    return provider


def build_engine(
    model: str,
    *,
    verbose: bool = False,
    roll_preset: int = DEFAULT_ROLL_PRESET,
) -> StoryEngine:
    """
    Build a StoryEngine for the target Gemma 4 variant. Fresh per case
    for isolation.
    """
    return StoryEngine(
        model=model,
        verbose=verbose,
        roll_mode="manual",
        manual_roll_provider=_preset_roll_provider(roll_preset),
    )


def _resolve_case_roll_value(case: Any, default_preset: int) -> int:
    outcome = getattr(case, "skill_check_outcome", None)
    if outcome is not None:
        normalized = str(outcome).strip().lower()
        if normalized in {"success", "succeed", "succeeds", "pass"}:
            return 20
        if normalized in {"fail", "fails", "failure"}:
            return 1

    raw = getattr(case, "preset_roll", None)
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass

    return default_preset



DEFAULT_STARTING_LOCATION = "Town Square"

def configure_engine_for_case(engine: StoryEngine, case: Any) -> None:
    """
    Apply a scenario's game-state setup to a freshly-built engine.
    """

    gs = engine.game_state
    world = engine.world

    # Story origin, Town Square is always visited. 
    mark_location_visited(gs, DEFAULT_STARTING_LOCATION, world)
    player_location = getattr(case, "player_location", "")
    if player_location:
        if not world.move_entity("Player", player_location):
            player = world.get_entity("Player")
            if player is not None:
                player.set_location(player_location)
        gs.player_location = player_location
        mark_location_visited(gs, player_location, world)

    # NPC positions, mirror move_npc: model.move_entity + npc_locations dict
    for npc_key, location in (getattr(case, "npc_locations", {}) or {}).items():
        if world.move_entity(npc_key, location):
            gs.npc_locations[npc_key] = location

    quest_flags = getattr(case, "quest_flags", None)
    if quest_flags:
        gs.quest_flags = dict(quest_flags)

    # Visited locations, go through mark_location_visited so that discovery follows the orchestrator's recompute logic.
    visited = getattr(case, "visited_keys", None) or []
    for key in visited:
        mark_location_visited(gs, key, world)

    # Discovered keys, a case may add extra discovered locations on top of what the recompute did.
    discovered_extras = getattr(case, "discovered_keys", None)
    if discovered_extras:
        extras = {str(k).strip() for k in discovered_extras if str(k).strip()}
        extras -= gs.visited_locations
        gs.discovered_locations |= extras

    # Conversation history
    history_lines = getattr(case, "conversation_history", None) or []
    for i, line in enumerate(history_lines):
        if i % 2 == 0:
            engine.history.add_player_turn(line)
        else:
            engine.history.add_dm_turn(line)

    # Story status
    story_status = getattr(case, "story_status", "")
    if story_status:
        engine.story_status = story_status



class BenchmarkRunner:
    def __init__(
        self,
        model: str,
        *,
        verbose: bool = False,
        roll_preset: int = DEFAULT_ROLL_PRESET,
    ):
        self.model = model
        self.verbose = verbose
        self.roll_preset = int(roll_preset)

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    # ----------------------------------------------------------
    # Phase 1
    # ----------------------------------------------------------
    def run_phase_one_test(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        print(f"  [phase_one] Running {len(PHASE_ONE_CASES)} cases...")

        for case in PHASE_ONE_CASES:
            self._log(f"    {case.id}: {case.description}")

            engine = build_engine(
                self.model,
                verbose=self.verbose,
                roll_preset=_resolve_case_roll_value(case, self.roll_preset),
            )
            configure_engine_for_case(engine, case)

            state = engine.state_builder.build(engine, case.player_input)
            turn_ctx = TurnContext.fresh(
                current_location=engine.game_state.player_location,
                roll_mode=engine.roll_mode,
                manual_roll_provider=engine.manual_roll_provider,
            )
            bind_turn_orchestration_ctx(engine.game_state, turn_ctx.as_dict())

            output = None
            error: Optional[str] = None
            iterations = 0
            try:
                with Timer() as t:
                    try:
                        output = engine.phase_one.run(PhaseOneInput(
                            state=state,
                            player_input=case.player_input,
                            turn_ctx=turn_ctx,
                            game_state=engine.game_state,
                            roll_mode=engine.roll_mode,
                            manual_roll_provider=engine.manual_roll_provider,
                        ))
                        iterations = len(output.loop_result.get("rounds", []))
                    except Exception as exc:
                        error = str(exc)
            finally:
                clear_turn_orchestration_ctx(engine.game_state)

            if output is not None:
                result = score_phase_one(
                    case=case,
                    finalize_payload=output.finalize_payload,
                    phase_one_tool_calls=output.phase_one_tool_calls,
                    loop_result=output.loop_result,
                    elapsed=t.elapsed,
                    iterations=iterations,
                    error=error,
                )
            else:
                result = score_phase_one(
                    case=case,
                    finalize_payload=None,
                    phase_one_tool_calls=[],
                    loop_result={},
                    elapsed=t.elapsed,
                    iterations=0,
                    error=error,
                )

            results.append(result)
            tag = "OK" if result["all_correct"] else "ISSUES"
            print(
                f"    {case.id} --> score={result['score']:.3f} "
                f"iterations={iterations} corrections={result['correction_count']} "
                f"({t.elapsed:.2f}s) [{tag}]"
            )
        return results

    # ----------------------------------------------------------
    # Narration
    # ----------------------------------------------------------
    def run_narration_test(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        print(f"  [narration] Running {len(NARRATION_CASES)} cases...")

        for case in NARRATION_CASES:
            self._log(f"    {case.id}: {case.description}")

            engine = build_engine(
                self.model,
                verbose=self.verbose,
                roll_preset=_resolve_case_roll_value(case, self.roll_preset),
            )

            configure_engine_for_case(engine, case)

            state = engine.state_builder.build(engine, case.player_input)

            output = None
            error: Optional[str] = None
            attempts = 1
            raw_output = ""

            try:
                with Timer() as t:
                    try:
                        output = engine.narration.run(NarrationInput(
                            state=state,
                            turn_summary=case.turn_summary,
                            narration_focus=case.narration_focus,
                            blocked_reason=case.blocked_reason,
                            action_tool_calls=case.action_tool_calls,
                            phase_one_tool_calls=case.phase_one_tool_calls,
                        ))
                        attempt_list = output.debug.get("attempts", [])
                        attempts = len(attempt_list) if attempt_list else 1
                        raw_output = (
                            attempt_list[-1].get("raw", "") if attempt_list else ""
                        )
                    except Exception as exc:
                        error = str(exc)
            finally:
                pass

            narrative = output.narrative if output is not None else ""
            result = score_narration(
                case=case,
                narrative=narrative,
                raw_output=raw_output,
                elapsed=t.elapsed,
                attempts=attempts,
                error=error,
            )

            # Capture per-attempt raw outputs for the report
            if output is not None:
                result["all_attempt_raws"] = [
                    a.get("raw", "") for a in output.debug.get("attempts", [])
                ]
            else:
                result["all_attempt_raws"] = []

            results.append(result)
            print(
                f"    {case.id} --> score={result['score']:.3f} "
                f"words={result['word_count']} attempts={attempts} "
                f"({t.elapsed:.2f}s)"
            )
        return results

    # ----------------------------------------------------------
    # Phase 2
    # ----------------------------------------------------------
    def run_phase_two_test(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        print(f"  [phase_two] Running {len(PHASE_TWO_CASES)} cases...")

        for case in PHASE_TWO_CASES:
            self._log(f"    {case.id}: {case.description}")

            engine = build_engine(
                self.model,
                verbose=self.verbose,
                roll_preset=_resolve_case_roll_value(case, self.roll_preset),
            )
            configure_engine_for_case(engine, case)

            state = engine.state_builder.build(engine, case.player_input)
            turn_ctx = TurnContext.fresh(
                current_location=engine.game_state.player_location,
                roll_mode=engine.roll_mode,
                manual_roll_provider=engine.manual_roll_provider,
            )

            turn_ctx.data["all_world_tool_calls"] = list(case.phase_one_tool_calls)
            turn_ctx.data["finalize"] = {
                "turn_summary": case.turn_summary,
                "narration_focus": case.narration_focus,
                "blocked_reason": case.blocked_reason,
            }
            bind_turn_orchestration_ctx(engine.game_state, turn_ctx.as_dict())

            world_before = build_runtime_state_snapshot(engine)

            output = None
            error: Optional[str] = None
            iterations = 0
            world_after: Dict[str, Any] = {}
            try:
                with Timer() as t:
                    try:
                        output = engine.phase_two.run(PhaseTwoInput(
                            state=state,
                            player_input=case.player_input,
                            turn_ctx=turn_ctx,
                            game_state=engine.game_state,
                            finalize_payload={
                                "turn_summary": case.turn_summary,
                                "narration_focus": case.narration_focus,
                                "blocked_reason": case.blocked_reason,
                            },
                            phase_one_tool_calls=case.phase_one_tool_calls,
                            narration=case.narration,
                            action_tool_calls=case.action_tool_calls,
                            world_before=world_before,
                        ))
                        iterations = len(output.loop_result.get("rounds", []))
                    except Exception as exc:
                        error = str(exc)
            finally:
                location_after = engine.game_state.player_location
                try:
                    world_after = build_runtime_state_snapshot(engine)
                except Exception:
                    world_after = {}
                clear_turn_orchestration_ctx(engine.game_state)

            if output is not None:
                result = score_phase_two(
                    case=case,
                    finalize_writes_payload=output.finalize_writes_payload,
                    phase_two_tool_calls=output.phase_two_tool_calls,
                    location_after=location_after,
                    loop_result=output.loop_result,
                    elapsed=t.elapsed,
                    iterations=iterations,
                    world_before=world_before,
                    world_after=world_after,
                    error=error,
                )
            else:
                result = score_phase_two(
                    case=case,
                    finalize_writes_payload=None,
                    phase_two_tool_calls=[],
                    location_after=location_after,
                    loop_result={},
                    elapsed=t.elapsed,
                    iterations=0,
                    world_before=world_before,
                    world_after=world_after,
                    error=error,
                )

            results.append(result)
            tag = "OK" if result["all_correct"] else "ISSUES"
            print(
                f"    {case.id} --> score={result['score']:.3f} "
                f"loc={location_after} iterations={iterations} "
                f"corrections={result['correction_count']} "
                f"({t.elapsed:.2f}s) [{tag}]"
            )
        return results


# ============================================================
# Per-model run
# ============================================================

ALL_TESTS = ["phase_one", "narration", "phase_two"]


def benchmark_model(
    model: str,
    *,
    tests: Optional[List[str]] = None,
    verbose: bool = False,
    roll_preset: int = DEFAULT_ROLL_PRESET,
) -> Dict[str, Any]:
    tests = tests or ALL_TESTS

    print(f"\n{'='*60}")
    print(f"  Model: {model}")
    print(f"  Tests: {tests}")
    print(f"  Roll preset: {roll_preset}")
    print(f"{'='*60}")

    runner = BenchmarkRunner(
        model=model,
        verbose=verbose,
        roll_preset=roll_preset,
    )
    test_map = {
        "phase_one": runner.run_phase_one_test,
        "narration": runner.run_narration_test,
        "phase_two": runner.run_phase_two_test,
    }

    test_results: Dict[str, Any] = {}
    overall_start = time.perf_counter()

    for test_name in tests:
        if test_name not in test_map:
            print(f"  [WARNING] Unknown test '{test_name}', skipping")
            continue
        case_results = test_map[test_name]()
        test_results[test_name] = {
            "results": case_results,
            "summary": summarize_results(case_results),
        }

    overall_elapsed = time.perf_counter() - overall_start

    all_results: List[Dict[str, Any]] = []
    for s in test_results.values():
        all_results.extend(s["results"])

    return {
        "model": model,
        "timestamp": datetime.now().isoformat(),
        "total_elapsed_s": round(overall_elapsed, 2),
        "tests": test_results,
        "overall": summarize_results(all_results),
    }


# ============================================================
# Output paths
# ============================================================

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def _model_json_path(model: str, timestamp: str) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    safe = model.replace("/", "_").replace(":", "_")
    return OUTPUT_DIR / f"{timestamp}_{safe}_results.json"


def _single_html_path(model: str, timestamp: str) -> Path:
    OUTPUT_DIR.mkdir(exist_ok=True)
    safe = model.replace("/", "_").replace(":", "_")
    return OUTPUT_DIR / f"{timestamp}_{safe}_report.html"


# ============================================================
# CLI entry point
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Orchestrator pipeline benchmark - runs one Gemma 4 variant at a time.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Run all three phase tests, save JSON + HTML\n"
            "  python3 -m benchmark.runner --model gemma4:31b\n\n"
            "  # JSON only\n"
            "  python3 -m benchmark.runner --model gemma4:e4b --no-html\n\n"
            "  # Specific phases only\n"
            "  python3 -m benchmark.runner --model gemma4:31b --tests phase_one narration\n\n"
            "  # Smallest variant for a quick smoke test\n"
            "  python3 -m benchmark.runner --model gemma4:e2b\n"
        ),
    )
    parser.add_argument("--model", required=True, help="Ollama tag for the Gemma 4 variant to benchmark (e.g. gemma4:31b)")
    parser.add_argument("--tests", nargs="*", choices=ALL_TESTS, default=None, help=f"Which phase tests to run (default: all -- {', '.join(ALL_TESTS)})")
    parser.add_argument("--no-html", action="store_true", help="Skip the HTML report (JSON only)")
    parser.add_argument("--verbose", action="store_true", help="Show detailed LLM output")
    parser.add_argument("--roll-preset", type=int, default=DEFAULT_ROLL_PRESET,
                        help=(
                            "d20 result returned for any skill_check or single-die roll_dice the model issues during a case."
                            "Must be in the range 1..20. Default: "f"{DEFAULT_ROLL_PRESET}. Lets the benchmark run "
                            "unattended without terminal roll prompts and keeps scoring reproducible across runs."
                        ))
    args = parser.parse_args()

    if not (1 <= args.roll_preset <= 20):
        parser.error("--roll-preset must be an integer between 1 and 20.")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    active_tests = args.tests or ALL_TESTS
    model = args.model

    try:
        result = benchmark_model(
            model,
            tests=active_tests,
            verbose=args.verbose,
            roll_preset=args.roll_preset,
        )
    except Exception as exc:
        print(f"\n[ERROR] Model '{model}' failed: {exc}")
        result = {"error": str(exc), "model": model, "provider": args.provider}

    json_path = _model_json_path(model, timestamp)
    json_path.write_text(json.dumps({model: result}, indent=2, default=str), encoding="utf-8")
    print(f"\nResults saved: {json_path}")

    if "error" not in result:
        _print_summary(model, result, active_tests)

    if not args.no_html:
        from .report import generate_report
        html_path = _single_html_path(model, timestamp)
        generate_report({model: result}, str(html_path))
        print(f"Report: {html_path}")
    else:
        print("HTML report skipped (--no-html).")

    print(
        f"\nTo compare with other runs:\n"
        f"  python3 -m benchmark.report {json_path} <other_results.json> ..."
    )


def _print_summary(model: str, data: Dict[str, Any], tests: List[str]) -> None:
    overall = data.get("overall", {})
    print(f"\n{'='*60}")
    print(f"  Results: {model}")
    print(f"{'='*60}")
    print(f"  {'Overall score':<22} {overall.get('mean_score', 0):.3f}")
    print(f"  {'Avg response time':<22} {overall.get('mean_elapsed_s', 0):.2f}s")
    print(f"  {'Avg attempts':<22} {overall.get('mean_attempts', 0):.2f}")
    print(f"  {'Avg iterations':<22} {overall.get('mean_iterations', 0):.2f}")
    print()
    for test in tests:
        summary = data.get("tests", {}).get(test, {}).get("summary", {})
        score = summary.get("mean_score", 0)
        n = summary.get("n", 0)
        print(f"  {test:<22} {score:.3f}  ({n} cases)")
    failed = overall.get("failed_cases", [])
    if failed:
        print(f"\n  Failed cases: {', '.join(failed)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
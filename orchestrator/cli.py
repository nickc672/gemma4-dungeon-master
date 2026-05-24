from __future__ import annotations
import argparse
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .app_config import get_default_model, get_roll_mode
from .runtime_flow.pipeline import StoryEngine
from .runtime_flow.session_state import write_session_checkpoint
from .world_state.tool_runtime import set_world_checkpoint_root
from .world_state.world_model import build_world_model

DEFAULT_MODEL = get_default_model()
DEFAULT_TRUNCATE_LIMIT = 200

@dataclass
class VerboseConfig:
    location: bool = True
    phase1: bool = True
    narrate_errors: bool = True
    phase2: bool = True
    changes: bool = True
    state_snapshot: bool = False
    prompts: bool = False
    narrate_memories: bool = True
    thinking: bool = False
    assistant_text: bool = False
    tool_ids: bool = False
    hook_notes: bool = False
    beat: bool = False
    raw_messages: bool = False

    # Field meanings:
#   location        - one-line before/after location, actors, items
#   phase1          - phase 1 tool calls, finalize summary, intended actions
#   phase2          - phase 2 tool calls and writes summary
#   narrate_errors  - narrate/intro retry error lines (silent on clean run)
#   changes         - every entity/item/location that changed this turn
#   state_snapshot  - full state block before and after (beat, connections, session summary, all scene fields)
#   prompts         - full prompt text sent to each phase
#   narrate_memories- just the Surfaced Memories block from the narration prompt
#   thinking        - model extended-thinking blocks
#   assistant_text  - assistant Decision Summary lines between tool calls
#   tool_ids        - tool call IDs in the tool output lines
#   hook_notes      - hook notes injected mid-conversation
#   beat            - beat current / next / guide lines
#   raw_messages    - full messages[] array sent to model (system + user + injected context + history)


def _default_world_model():
    return build_world_model()

def _prompt_manual_d20_roll(request: Dict[str, Any]) -> int:
    args = dict(request.get("arguments") or {})
    entity = str(args.get("entity_key", "Player"))
    skill = str(args.get("skill", "check"))
    dc = args.get("dc")
    phase = str(request.get("phase") or "").strip()
    phase_prefix = f"{phase} " if phase else ""

    while True:
        raw = input(f"[Roll] {phase_prefix}{entity} {skill} vs DC {dc} (enter d20 1-20): ").strip()
        if raw.lower() in {"quit", "exit"}:
            raise RuntimeError("Player aborted manual roll input.")
        try:
            value = int(raw)
        except ValueError:
            print("Enter an integer from 1 to 20.")
            continue
        if 1 <= value <= 20:
            return value
        print("Enter a d20 result between 1 and 20.")

def truncate(text: str, limit: int = DEFAULT_TRUNCATE_LIMIT) -> str:
    """
    Shorten long text blocks for terminal display.
    """
    if not text:
        return text
    text = text.lstrip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated {len(text) - limit} chars]"


def _ok(result: Dict[str, Any]) -> bool:
    if "ok" in result:
        return bool(result["ok"])
    return bool(result.get("success", False))


def _scene_line(scene: Dict[str, Any]) -> str:
    loc = scene.get("current_location") or scene.get("location") or "?"
    actors = [a for a in (scene.get("actors_here") or []) if str(a).lower() != "player"]
    items = list(scene.get("items_here") or [])
    parts = [f"loc={loc}"]
    if actors:
        parts.append(f"actors={actors}")
    if items:
        parts.append(f"items={items}")
    return "  " + "  ".join(parts)


# =====================================
# Raw Messages Printer
# =====================================

def _print_raw_messages(label: str, phase_trace: Dict[str, Any]) -> None:
    """
    Print the full messages array that was sent to the model for this phase.
    Expects pipeline.py to have stored the messages list under messages_sent
    in the phase trace dict before making the API call.

    Each message is printed with its role and the full content. If content is
    a list of blocks (tool calls, tool results, text blocks) each block is
    printed separately so the structure is easy to read.
    """
    messages = phase_trace.get("messages")
    if not messages:
        print(f"\n[{label} RAW MESSAGES]  not available")
        print("  Add this to pipeline.py before the API call:")
        print('  phase_trace["messages"] = messages')
        return

    print(f"\n[{label} RAW MESSAGES]  count={len(messages)}")
    for i, msg in enumerate(messages):
        role = msg.get("role", "?")
        content = msg.get("content", "")

        print(f"\n  -- message {i}  role={role} --")

        if isinstance(content, str):
            # Plain string content: print as-is
            print(f"  {content}")

        elif isinstance(content, list):
            # Structured content blocks
            for j, block in enumerate(content):
                btype = block.get("type", "?")
                print(f"  block {j}  type={btype}")

                if btype == "text":
                    text = block.get("text", "")
                    print(f"    {text}")

                elif btype == "tool_use":
                    name = block.get("name", "?")
                    call_id = block.get("id", "")
                    input_args = block.get("input") or {}
                    print(f"    name={name}  id={call_id}")
                    print(f"    input={json.dumps(input_args, indent=6, ensure_ascii=False)}")

                elif btype == "tool_result":
                    call_id = block.get("tool_use_id", "")
                    result_content = block.get("content", "")
                    print(f"    tool_use_id={call_id}")
                    if isinstance(result_content, str):
                        print(f"    content={result_content}")
                    elif isinstance(result_content, list):
                        for rb in result_content:
                            print(f"    content block: {json.dumps(rb, ensure_ascii=False)}")
                    else:
                        print(f"    content={json.dumps(result_content, ensure_ascii=False)}")

                else:
                    print(f"    {json.dumps(block, ensure_ascii=False)}")
        else:
            print(f"  {json.dumps(content, ensure_ascii=False)}")


# =====================================
# State-Changes Section
# =====================================

def _print_changes(trace: Dict[str, Any]) -> None:
    """
    Print every entity, item, and location that changed this turn.
    Pulls from trace["RECONCILIATION"]["delta"].
    """
    recon = trace.get("RECONCILIATION") or {}
    delta = recon.get("delta") or {}
    if not delta:
        return

    lines: list[str] = []

    # Player location change
    ploc = delta.get("player_location") or {}
    before_loc = str(ploc.get("before") or "").strip()
    after_loc = str(ploc.get("after") or "").strip()
    if before_loc and after_loc and before_loc != after_loc:
        lines.append(f"  Player location   : {before_loc} -> {after_loc}")

    # NPC location changes
    for entry in delta.get("npc_location_changes") or []:
        npc = str(entry.get("npc") or "").strip()
        before = str(entry.get("before") or "").strip()
        after = str(entry.get("after") or "").strip()
        if npc and before != after:
            lines.append(f"  {npc} location   : {before} -> {after}")

    # Entity location changes (catches anything the NPC list may miss)
    seen_entity_locs = set()
    for entry in delta.get("entity_location_changes") or []:
        entity = str(entry.get("entity") or "").strip()
        etype = str(entry.get("entity_type") or "").strip()
        before = str(entry.get("before") or "").strip()
        after = str(entry.get("after") or "").strip()
        if entity and before != after and entity not in seen_entity_locs:
            seen_entity_locs.add(entity)
            tag = f"[{etype}] " if etype else ""
            lines.append(f"  {tag}{entity} location   : {before} -> {after}")

    # Item holder changes
    for entry in delta.get("item_holder_changes") or []:
        item = str(entry.get("item") or "").strip()
        bef = entry.get("before") or {}
        aft = entry.get("after") or {}
        before_str = f"{bef.get('holder_kind')}={bef.get('holder_key')}"
        after_str = f"{aft.get('holder_kind')}={aft.get('holder_key')}"
        if item and before_str != after_str:
            lines.append(f"  {item} holder   : {before_str} -> {after_str}")

    # Quest flag changes
    for entry in delta.get("quest_flag_changes") or []:
        flag = str(entry.get("flag") or "").strip()
        before = entry.get("before")
        after = entry.get("after")
        if flag and before != after:
            lines.append(f"  flag {flag}   : {before} -> {after}")

    # Memory changes - show added and removed sentences per entity
    for entry in delta.get("memory_changes") or []:
        entity = str(entry.get("entity") or "").strip()
        added = list(entry.get("added") or [])
        removed = list(entry.get("removed") or [])
        if not entity:
            continue
        for sentence in added:
            lines.append(f"  {entity} memory +  : {truncate(sentence, 160)}")
        for sentence in removed:
            lines.append(f"  {entity} memory -  : {truncate(sentence, 160)}")

    if lines:
        print("\n[CHANGES]")
        for line in lines:
            print(line)


# =====================================
# Phase Tool-Call Printer (shared by phase 1 and 2)
# =====================================

def _print_phase_rounds(rounds: list, cfg: VerboseConfig) -> None:
    for rnd in rounds:
        iteration = rnd.get("iteration", "?")
        tool_calls = rnd.get("tool_calls") or []
        tool_results = rnd.get("tool_results") or []
        block = rnd.get("response_block_reason") or rnd.get("stop_block_reason") or ""
        thinking = rnd.get("assistant_thinking") or ""
        assistant_text = rnd.get("assistant_text") or ""
        hook_notes_list = rnd.get("hook_notes") or []

        has_content = (
            tool_calls
            or block
            or (cfg.thinking and thinking)
            or (cfg.assistant_text and assistant_text)
        )
        if not has_content:
            continue

        print(f"  iter {iteration}:")

        if cfg.thinking and thinking:
            print(f"    THINKING: {truncate(thinking, 300)}")

        if cfg.assistant_text and assistant_text:
            print(f"    ASSISTANT: {truncate(assistant_text, 200)}")

        for call in tool_calls:
            name = call.get("name", "?")
            args = call.get("arguments") or {}
            call_id = call.get("id") or ""

            result_payload = {}
            for tr in tool_results:
                if tr.get("name") == name:
                    result_payload = tr.get("result") or {}
                    break

            success = _ok(result_payload)
            reason = str(result_payload.get("reason") or result_payload.get("error") or "").strip()
            args_short = truncate(json.dumps(args, ensure_ascii=True), 120)
            status_tag = "ok" if success else "FAIL"

            id_prefix = f"[{call_id}] " if cfg.tool_ids and call_id else ""
            line = f"    {id_prefix}{name}({args_short}) -> {status_tag}"
            if reason:
                line += f": {truncate(reason, 100)}"
            print(line)

        if cfg.hook_notes and hook_notes_list:
            for note in hook_notes_list:
                print(f"    hook: {truncate(str(note), 160)}")

        if block:
            print(f"    BLOCKED: {truncate(str(block), 160)}")


# =====================================
# Full State Snapshot
# =====================================

def _print_state_snapshot(label: str, state: Dict[str, Any], cfg: VerboseConfig) -> None:
    print(f"\n{label}")
    if cfg.beat:
        print(f"  beat current : {truncate(state.get('beat_current', ''), 120)}")
        print(f"  beat next    : {truncate(state.get('beat_next', ''), 120)}")
        print(f"  beat guide   : {truncate(state.get('beat_guide', ''), 120)}")
    scene = state.get("scene") or {}
    print(f"  location     : {scene.get('current_location')}")
    print(f"  connections  : {scene.get('connections')}")
    print(f"  actors       : {scene.get('actors_here')}")
    print(f"  items        : {scene.get('items_here')}")
    print(f"  status       : {truncate(str(scene.get('status') or ''), 160)}")
    print(f"  summary      : {truncate(str(scene.get('session_summary') or ''), 160)}")


# =====================================
# Main Verbose Printer
# =====================================

def print_llm_verbose(turn_number: int, trace: Dict[str, Any], cfg: VerboseConfig | None = None) -> None:
    if cfg is None:
        cfg = VerboseConfig()

    print(f"\n=== TURN {turn_number} ===")

    # Full state snapshot before
    state_before = trace.get("STATE_BEFORE")
    if cfg.state_snapshot and state_before:
        _print_state_snapshot("STATE BEFORE", state_before, cfg)
    elif cfg.location and state_before:
        print(f"BEFORE:{_scene_line(state_before.get('scene', {}))}")

    # Beat info when state_snapshot is off but beat is on
    if cfg.beat and not cfg.state_snapshot and state_before:
        print(f"  beat: {truncate(state_before.get('beat_current', ''), 120)}")

    # Phase 1
    p1 = trace.get("PHASE_ONE")
    if cfg.phase1 and isinstance(p1, dict):
        rounds = p1.get("rounds") or []
        status = p1.get("status") or "?"
        print(f"\n[PHASE 1]  status={status}  iterations={len(rounds)}")

        if cfg.prompts and p1.get("prompt"):
            print(f"  PROMPT:\n{p1['prompt']}\n")

        if cfg.raw_messages:
            _print_raw_messages("PHASE 1", p1)

        _print_phase_rounds(rounds, cfg)

        finalize = p1.get("finalize") or {}
        if finalize:
            summary = truncate(str(finalize.get("turn_summary") or ""), 200)
            blocked = str(finalize.get("blocked_reason") or "").strip()
            focus = truncate(str(finalize.get("narration_focus") or ""), 120)
            actions = finalize.get("intended_actions") or []
            print(f"  summary : {summary}")
            if focus:
                print(f"  focus   : {focus}")
            if blocked:
                print(f"  BLOCKED : {blocked}")
            for a in actions:
                kind = a.get("kind", "?")
                dest = a.get("destination") or ""
                target = a.get("target") or ""
                mem = truncate(str(a.get("memory_text") or ""), 80)
                parts = [kind]
                if dest:
                    parts.append(f"dest={dest}")
                if target:
                    parts.append(f"target={target}")
                if mem:
                    parts.append(f'mem="{mem}"')
                print(f"  action  : {' '.join(parts)}")

    # Narrate - only print when there were retry errors
    narrate = trace.get("NARRATE")
    if cfg.narrate_errors and isinstance(narrate, dict):
        attempts = narrate.get("attempts") or []
        retry_attempts = [a for a in attempts if a.get("error")]
        if retry_attempts:
            print(f"\n[NARRATE]  retries={len(retry_attempts)}")
            for a in retry_attempts:
                print(f"  attempt {a.get('attempt')}: {truncate(str(a.get('error') or ''), 160)}")
        if cfg.prompts and narrate.get("prompt"):
            print(f"\n[NARRATE] PROMPT:\n{narrate['prompt']}\n")
        if cfg.narrate_memories and narrate.get("prompt"):
            prompt_text = str(narrate["prompt"])
            # Surfaced Memories header
            marker = "# Surfaced Memories"
            start = prompt_text.find(marker)
            if start >= 0:
                rest = prompt_text[start:]
                end_marker = rest.find("\n# ", len(marker))
                section = rest[:end_marker] if end_marker > 0 else rest
                print(f"\n[NARRATE] {section.rstrip()}\n")
            else:
                print("\n[NARRATE] # Surfaced Memories\n(none surfaced this turn)\n")
        if cfg.raw_messages:
            _print_raw_messages("NARRATE", narrate)

    # Phase 2
    p2 = trace.get("PHASE_TWO")
    if cfg.phase2 and isinstance(p2, dict):
        rounds = p2.get("rounds") or []
        status = p2.get("status") or "?"
        print(f"\n[PHASE 2]  status={status}  iterations={len(rounds)}")

        if cfg.prompts and p2.get("prompt"):
            print(f"  PROMPT:\n{p2['prompt']}\n")

        if cfg.raw_messages:
            _print_raw_messages("PHASE 2", p2)

        _print_phase_rounds(rounds, cfg)

        fw = p2.get("finalize_writes") or {}
        writes_summary = truncate(str(fw.get("writes_summary") or ""), 160)
        if writes_summary:
            print(f"  writes  : {writes_summary}")

    # Movement blocked flag
    if trace.get("MOVEMENT_BLOCKED"):
        print("\n  [!] movement was blocked")

    # State changes (memory, location, items, flags)
    if cfg.changes:
        _print_changes(trace)

    # Full state snapshot after
    state_after = trace.get("STATE_AFTER")
    if cfg.state_snapshot and state_after:
        _print_state_snapshot("STATE AFTER", state_after, cfg)
    elif cfg.location and state_after:
        print(f"\nAFTER: {_scene_line(state_after.get('scene', {}))}")

    print(f"=== END TURN {turn_number} ===\n")


# =====================================
# Argument Parsing
# =====================================

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Story exploration demo.")
    defaults = _default_world_model()

    parser.add_argument(
        "--model",
        default=None,
        help="Ollama tag for the model to run (default: configured default in app_config.json)",
    )

    parser.add_argument(
        "--starting-location",
        default=defaults.starting_location,
        help="Override the authored world-model starting location",
    )

    parser.add_argument(
        "--starting-state",
        help="Override the starting state text shown to the model",
    )

    parser.add_argument(
        "--session-name",
        default="session",
        help="Name for this play session (used in state folder)",
    )

    parser.add_argument(
        "--state-root",
        default="state",
        help="Directory root for session snapshots",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help=(
            "Enable verbose turn output. Which sections are shown is "
            "controlled by the VerboseConfig dataclass in cli.py."
        ),
    )

    return parser


# =====================================
# Main Application
# =====================================

def main() -> None:
    args = build_arg_parser().parse_args()
    world_defaults = _default_world_model()

    # Keep logging quiet; verbose output is handled manually
    logging.basicConfig(level=logging.WARNING)

    verbose_cfg = VerboseConfig()

    if args.verbose:
        print("In verbose mode\n")
        active = [k for k, v in verbose_cfg.__dict__.items() if v]
        inactive = [k for k, v in verbose_cfg.__dict__.items() if not v]
        print(f"  showing : {', '.join(active)}")
        print(f"  hidden  : {', '.join(inactive)}")
        print()

    configured_roll_mode = get_roll_mode()

    engine = StoryEngine(
        model=args.model,
        verbose=args.verbose,
        starting_location=args.starting_location,
        starting_state=args.starting_state or world_defaults.starting_state,
        roll_mode=configured_roll_mode,
        manual_roll_provider=_prompt_manual_d20_roll if configured_roll_mode == "manual" else None,
    )

    # ----- Session Folder -----

    session_dir: Path | None = None

    if args.state_root:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = Path(args.state_root) / f"{stamp}_{args.session_name}"
        session_dir.mkdir(parents=True, exist_ok=True)
        set_world_checkpoint_root(engine.game_state, session_dir / "checkpoints")
        print(f"Session snapshots will be written to: {session_dir}")

    # ----- Intro -----

    print("Story explorer. Type 'quit' to leave.")

    try:
        intro = engine.generate_intro()
        print(f"\n{intro['ic']}\n")
    except Exception:
        print(f"\n[Intro] {engine.starting_state}\n")

    # Save initial snapshot
    if session_dir:
        try:
            write_session_checkpoint(session_dir, engine, 0)
        except Exception as exc:
            logging.warning("Failed to write initial state snapshot: %s", exc)

    # ----- Game Loop -----

    while True:
        try:
            player_line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not player_line:
            continue

        if player_line.lower() in {"quit", "exit"}:
            print("Goodbye.")
            break

        turn: Dict[str, Any] = engine.run_turn(player_line)

        # Verbose LLM Trace
        if args.verbose and turn.get("llm_trace"):
            print_llm_verbose(turn["turn"], turn["llm_trace"], verbose_cfg)

        # Narrative Output
        print(f"\n{turn['narration']['ic']}\n")

        # Save snapshot
        if session_dir:
            try:
                write_session_checkpoint(session_dir, engine, int(turn.get("turn", engine.turn_index)))
            except Exception as exc:
                logging.warning("Failed to write state snapshot: %s", exc)


if __name__ == "__main__":
    main()

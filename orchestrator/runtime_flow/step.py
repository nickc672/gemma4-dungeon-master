from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union
import re

from orchestrator.llm_interaction.adapter import LLMAdapter, LLMError

# =========================
# Core Step Object
# =========================

@dataclass
class LLMStep:
    """
    Defines a single structured LLM operation.
    """
    name: str
    system_prompt: str
    tags: set[str]
    use_cot: bool = True
    max_attempts: int = 3
    validator: Optional[Callable[[Dict[str, str]], None]] = None
    parser: Optional[Callable[[Dict[str, str]], Any]] = None

    def run(
        self,
        adapter: LLMAdapter,
        payload_text: str,
        *,
        tools: Optional[Sequence[Union[Mapping[str, Any], Any, Callable]]] = None,
        tool_executor: Optional[Callable[[str, Mapping[str, Any]], Any]] = None,
    ) -> tuple[Any, Dict[str, Any]]:
        if adapter.verbose:
            print(f"[STEP-ENTER] {self.name} run() entered")

        tags = set(self.tags)
        if self.use_cot:
            tags |= {"thoughts"}

        attempts: List[Dict[str, Any]] = []

        # step-local retry guard (NO adapter mutation)
        forced_retry_pending = (
            adapter.verbose
            and getattr(adapter, "force_retry_stage", None) == self.name
        )

        for attempt_num in range(1, self.max_attempts + 1):
            if adapter.verbose:
                print(f"[LLM] Step '{self.name}' — attempt {attempt_num}")

            try:
                raw, adapter_attempts = adapter.request_text(self.name, self.system_prompt, payload_text)
            except Exception as exc:
                # Adapter-level failure (e.g., all retries exhausted with empty responses)
                attempts.append({
                    "attempt": attempt_num,
                    "prompt": payload_text,
                    "raw": "",
                    "sections": {},
                    "error": f"Adapter error: {exc}",
                })
                
                if adapter.verbose:
                    print(f"[STEP-RETRY] {self.name}: adapter error: {exc}")
                
                payload_text += (
                    f"\n\n(Note: previous attempt failed: {exc}. "
                    "Please provide a valid response.)"
                )
                continue
            
            # Record failed adapter attempts (empty responses)
            for adapter_attempt in adapter_attempts[:-1]:  # All but the last one
                if not adapter_attempt["success"]:
                    attempts.append({
                        "attempt": len(attempts) + 1,
                        "prompt": payload_text,
                        "raw": adapter_attempt.get("content", ""),
                        "sections": {},
                        "error": "Empty response from LLM",
                    })
            
            sections = parse_sections(raw, tags)

            try:
                if self.validator:
                    self.validator(sections)

                parsed = self.parser(sections) if self.parser else sections

                # FORCE ONE STEP-LEVEL RETRY
                if forced_retry_pending:
                    forced_retry_pending = False  # only once

                    if adapter.verbose:
                        print(f"[STEP-RETRY] forcing retry in step '{self.name}'")

                    raise ValueError("Forced step-level retry (intentional)")

            except Exception as exc:
                attempts.append({
                    "attempt": len(attempts) + 1,
                    "prompt": payload_text,
                    "raw": raw,
                    "sections": sections,
                    "error": str(exc),
                })

                if adapter.verbose:
                    print(f"[STEP-RETRY] {self.name}: {exc}")

                payload_text += (
                    f"\n\n(Note: last output was invalid: {exc}. "
                    "Please follow the required format.)"
                )
                continue

            # Success!
            attempts.append({
                "attempt": len(attempts) + 1,
                "prompt": payload_text,
                "raw": raw,
                "sections": sections,
                "parsed": parsed,
            })

            return parsed, {"attempts": attempts}

        raise LLMError(f"Step '{self.name}' failed after {self.max_attempts} attempts.")



# =========================
# Parsing Helpers
# =========================

def parse_sections(text: str, tags: set[str]) -> Dict[str, str]:
    result: Dict[str, List[str]] = {}
    current: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()

        matched = None
        for tag in tags:  # ← no need to sort
            prefix = f"{tag}:"
            if lower.startswith(prefix):
                matched = tag
                content = stripped[len(prefix):].strip()
                result.setdefault(tag, []).append(content)
                current = tag
                break

        if matched is None and current and stripped:
            result[current].append(stripped)

    return {
        tag: " ".join(lines).strip()
        for tag, lines in result.items()
        if lines
    }





# =========================
# Step-Specific Parsers
# =========================

def parse_narrative(sections: Dict[str, str]) -> str:
    return sections.get("narrative", "").strip()


# =========================
# Validators
# =========================

def validate_narration_step(sections: Dict[str, str]) -> None:
    """
    FIX: Provide more detailed error message when narrative section is missing
    to help the LLM understand what went wrong.
    """
    narrative = sections.get("narrative", "")

    if not narrative:
        # Check if there's raw text that might be narrative without the label
        all_text = " ".join(sections.values())
        if len(all_text) > 50:  # Has substantial content but wrong format
            raise ValueError(
                "Missing Narrative section. You wrote content but forgot the 'Narrative:' label. "
                "You MUST start your narrative with 'Narrative:' exactly as shown in the format."
            )
        else:
            raise ValueError(
                "Missing Narrative section. You must provide a 'Narrative:' section with story prose."
            )

    if re.search(r"\b1\)", narrative) or re.search(r"\b2\)", narrative):
        raise ValueError("Narrative contains numbered choices. Do not offer explicit choices to the player.")

    # Narration must never defer checks/rolls back to the player.
    lower = narrative.lower()
    asks_for_roll = (
        re.search(r"\broll\b", lower)
        or re.search(r"\b(check|skill check|perception check|investigation check|dc)\b", lower)
    )
    defers_for_roll = (
        re.search(r"\b(i('| a)?ll need|i will need|need|before i can|provide|give me|make)\b", lower)
        and asks_for_roll
    ) or re.search(r"\broll\s+(a|an|your)\b", lower)
    if defers_for_roll:
        raise ValueError(
            "Narrative asked the player to roll/check. Do not request rolls in narration; use resolved mechanics only."
        )

    # Also reject asking for stat bonus/modifier input in narration.
    asks_for_modifier = (
        re.search(r"\b(bonus|modifier)\b", lower)
        and re.search(r"\b(what|tell me|let me know|provide|give)\b", lower)
    )
    dm_roll_language = re.search(
        r"\b(i\s+(roll|rolled|will roll|can roll)|let me roll|so i can roll)\b",
        lower,
    )
    if asks_for_modifier or dm_roll_language:
        raise ValueError(
            "Narrative requested bonus/modifier input or attempted DM-side rolling text. "
            "Resolve checks in mechanics tools instead."
        )

__all__ = [
    "LLMStep",
    "parse_narrative",
    "validate_narration_step",
]

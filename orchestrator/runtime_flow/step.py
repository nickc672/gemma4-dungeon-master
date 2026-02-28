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

def parse_intent(sections: Dict[str, str]) -> Dict[str, Any]:
    action = sections.get("action", "").strip().lower()

    valid_actions = {"move", "talk", "inspect", "take", "use", "wait", "attack", "meta_question", "other"}
    action_category = action if action in valid_actions else "other"
    if not action:
        action = "other"

    targets_raw = sections.get("targets", "").strip()
    targets = [t.strip() for t in targets_raw.split(",") if t.strip() and t.strip().lower() not in {"none", "empty", ""}]

    return {
        "action": action,
        "action_category": action_category,
        "targets": targets,
    }


def parse_focus(sections: Dict[str, str]) -> List[str]:
    raw = sections.get("focus", "")
    return [t.strip() for t in raw.split(",") if t.strip()]


def parse_status(sections: Dict[str, str]) -> str:
    return sections.get("status", "").strip()


def parse_narrative(sections: Dict[str, str]) -> str:
    return sections.get("narrative", "").strip()


# =========================
# Validators
# =========================

def validate_validation_step(sections: Dict[str, str]) -> None:
    verdict = sections.get("verdict", "").lower()
    advance = sections.get("advance", "").lower()

    if verdict not in {"approve", "revise"}:
        raise ValueError("Verdict must be approve or revise.")

    if not (advance.startswith("y") or advance.startswith("n")):
        raise ValueError("Advance must be yes or no.")


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

__all__ = [
    "LLMStep",
    "parse_intent",
    "parse_focus",
    "parse_status",
    "parse_narrative",
    "validate_validation_step",
    "validate_narration_step",
]

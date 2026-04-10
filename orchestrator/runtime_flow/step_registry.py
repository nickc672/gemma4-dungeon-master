from .step import (
    LLMStep,
    parse_intent,
    parse_status,
    parse_narrative,
    validate_validation_step,
    validate_narration_step,
)

from ..llm_interaction.prompt_texts import (
    INTENT_PROMPT,
    PLAN_PROMPT,
    NARRATE_PROMPT,
    VALIDATE_PROMPT,
    STATUS_PROMPT,
    INTRO_PROMPT,
)


def build_steps():

    return {
        "intent": LLMStep(
            name="intent_parser",
            system_prompt=INTENT_PROMPT,
            tags={"action", "targets"},
            use_cot=False,
            max_attempts=3,
            parser=parse_intent,
        ),
        "plan": LLMStep(
            name="plan",
            system_prompt=PLAN_PROMPT,
            tags={"plan"},
            use_cot=True,
            parser=lambda s: s.get("plan") or "",
        ),

        "status": LLMStep(
            name="status",
            system_prompt=STATUS_PROMPT,
            tags={"status"},
            use_cot=True,
            parser=parse_status,
        ),

        "validate": LLMStep(
            name="validate",
            system_prompt=VALIDATE_PROMPT,
            tags={"verdict", "notes", "advance"},
            use_cot=True,
            validator=validate_validation_step,
            parser=lambda s: (
                s.get("verdict", "approve"),
                s.get("notes", ""),
                s.get("advance", "").lower().startswith("y"),
            ),
        ),

        "narrate": LLMStep(
            name="narrate",
            system_prompt=NARRATE_PROMPT,
            tags={"narrative"},
            use_cot=True,
            validator=validate_narration_step,
            parser=parse_narrative,
        ),

        "intro": LLMStep(
            name="intro",
            system_prompt=INTRO_PROMPT,
            tags={"narrative", "recap"},
            use_cot=True,
            validator=validate_narration_step,
            parser=lambda s: {
                "narrative": parse_narrative(s),
                "recap": (s.get("recap") or "").strip(),
            },
        ),
    }

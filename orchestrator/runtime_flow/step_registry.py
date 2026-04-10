from .step import (
    LLMStep,
    parse_narrative,
    validate_narration_step,
)

from ..llm_interaction.prompt_texts import (
    NARRATE_PROMPT,
    INTRO_PROMPT,
)


def build_steps():

    return {
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

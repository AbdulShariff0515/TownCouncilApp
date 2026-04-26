# utils/action_explanation_ai.py

"""
AI helper for explaining case actions to residents in plain language.
This does NOT decide actions — it only explains them.
"""

def build_action_explanation_prompt(
    action_label: str,
    case_category: str
):
    return f"""
You are assisting a Town Council in explaining case updates to residents.

An action has been taken on a case.

Action taken:
- {action_label}

Case category:
- {case_category}

Task:
Write a single clear paragraph explaining what this action means for the resident.

Rules:
- Use calm, professional, reassuring language
- Do NOT promise timelines
- Do NOT assign blame
- Do NOT mention internal systems or workflows
- State clearly if no action is required from the resident
- Keep it under 80 words
""".strip()


def generate_action_explanation(
    action_label: str,
    case_category: str,
    call_ai_function
):
    """
    call_ai_function should be your existing OpenAI / LLM call function
    that accepts a prompt and returns text.
    """
    prompt = build_action_explanation_prompt(
        action_label,
        case_category
    )

    explanation = call_ai_function(prompt)
    return explanation.strip()
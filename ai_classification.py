import os
import json
from openai import OpenAI

# Initialise OpenAI client
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")


def call_llm(prompt: str) -> str:
    """
    Sends a prompt to the LLM and returns raw text output.
    """

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You are a helpful and precise assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_completion_tokens=500
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        # Centralised AI failure handling
        raise RuntimeError(f"AI service error: {str(e)}")


def classify_issue_ai(description: str, location: str | None = None):
    """
    Classifies a town council issue using AI.
    Returns a structured dictionary.
    """

    if not description or len(description.strip()) < 15:
        raise ValueError("Description too short for AI classification")

    prompt = f"""
You are classifying a Town Council service case.

Issue description:
{description}

Location:
{location or "Not provided"}

Tasks:
1. Determine the most suitable primary category
2. Identify a specific sub-category
3. Assign priority: Low / Medium / High / Urgent
4. Assign severity: Minor / Moderate / Major / Critical
5. Suggest the handling unit
6. Provide a confidence score between 0 and 1

Respond ONLY in valid JSON with these keys:
category, sub_category, priority, severity, handling_unit, confidence
"""

    response_text = call_llm(prompt)

    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        raise ValueError("AI response is not valid JSON")

    return result
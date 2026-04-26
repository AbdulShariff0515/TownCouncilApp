# notifications.py

from dotenv import load_dotenv
load_dotenv()   # ✅ THIS IS THE KEY FIX

from db import get_submission_by_ref
from email_utils import (
    send_email,
    generate_case_action_update_email,
)


# ------------------------------------------------------------
# ✅ AI rewrite helper (ADD THIS HERE)
# ------------------------------------------------------------
def rewrite_action_notes_for_resident(action_notes: str) -> str:
    """
    Rewrites internal officer notes into a resident-friendly update.
    Safe fallback if AI is unavailable.
    """
    if not action_notes or not action_notes.strip():
        return action_notes
    
    try:
        import os
        from openai import OpenAI

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        prompt = (
            "You must write a NEW email update to a resident.\n\n"
            "Rules (MANDATORY):\n"
            "- Do NOT reuse any sentences or phrasing from the input\n"
            "- Do NOT sound like internal notes or a memo\n"
            "- Write as a Town Council officer addressing a resident\n"
            "- Use clear, reassuring, non-technical language\n"
            "- 2 short paragraphs maximum\n\n"
            "Internal officer notes (FOR CONTEXT ONLY, DO NOT COPY):\n"
            f"{action_notes}"
        )


        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )

        rewritten = response.choices[0].message.content.strip()
        return rewritten or action_notes
        
        if rewritten.strip().lower() == action_notes.strip().lower():
            return (
                "We would like to provide you with an update regarding your case. "
                "If you have any feedback or additional information to share, "
                "please let us know."
            )

    except Exception:
        # ✅ Never block sending email
        return action_notes

# ------------------------------------------------------------
# Existing function (MODIFY INSIDE, not move)
# ------------------------------------------------------------

def notify_resident_of_action(
    case_id: str,
    action_type: str,
    action_notes: str,
    new_status: str,
):
    """
    Sends a resident an email update when an officer records an action.
    """

    case = get_submission_by_ref(case_id)
    if not case:
        return

    # Respect consent
    if not case.get("consent"):
        return

    resident_email = case.get("contact")
    if not resident_email:
        return

    subject, body = generate_case_action_update_email(
        resident_name=case.get("name"),
        ref_id=case_id,
        action_type=action_type,
        action_notes=action_notes,
        new_status=new_status,
    )

    send_email(resident_email, subject, body)
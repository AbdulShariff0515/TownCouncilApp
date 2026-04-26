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
            
            "You are a Town Council officer writing an email update to a resident.\n\n"
            "Rules:\n"
            "- Do NOT copy or reuse the officer's wording\n"
            "- Write in clear, polite, reassuring language\n"
            "- Maximum 2 short paragraphs\n"
            "- Do not include internal or technical details\n\n"
            "Internal officer notes for context only:\n"
            f"{action_notes}"

        )


        response = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )

        rewritten = response.choices[0].message.content.strip()

        # ✅ Safety check
        if not rewritten or rewritten.lower() == action_notes.lower():
            return (
                "We would like to provide you with an update on your feedback. "
                "Our team has taken the necessary action, and we will continue "
                "to monitor the situation. Thank you for your patience."
            )

        return rewritten


    except Exception:
        # ✅ ✅ Always fail gracefully
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
    
    # ✅ AI rewrites internal notes into resident-friendly language
    resident_friendly_notes = rewrite_action_notes_for_resident(action_notes)

    # ✅ Generate email using AI-rewritten content
    subject, body = generate_case_action_update_email(
        resident_name=case.get("name"),
        ref_id=case_id,
        action_type=action_type,
        action_notes=resident_friendly_notes,
        new_status=new_status,


    )

    send_email(resident_email, subject, body)

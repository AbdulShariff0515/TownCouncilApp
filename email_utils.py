"""
email_utils.py

Utilities for generating acknowledgement emails and sending them via Gmail SMTP.
Designed for use with Streamlit + Gmail App Passwords.
"""

import smtplib
from email.message import EmailMessage
import os

# ─────────────────────────────────────────────
# Acknowledgement email generator
# ─────────────────────────────────────────────

def generate_acknowledgement_email(
    resident_name: str,
    issue_category: str,
    interim_advice: list
):
    subject = "Acknowledgement of Your Feedback – Town Council"

    advice_block = "\n".join([f"- {item}" for item in interim_advice])

    body = f"""
Dear {resident_name or 'Resident'},

Thank you for contacting the Town Council regarding the issue reported within your estate.
We acknowledge receipt of your feedback and appreciate you bringing this matter to our attention.

Our team will review the information submitted and conduct the necessary assessment.
Where required, relevant service partners will be engaged to follow up on the matter.

In the meantime, you may wish to consider the following general precautions:
{advice_block}

We appreciate your patience and understanding as we work to maintain a safe and
well-managed living environment for all residents.

Should further information be required, our officers may contact you using the details provided.

Yours sincerely,
Town Council
Estate Management Team

---
AI-generated draft acknowledgement for officer review.
""".strip()

    return subject, body


# ─────────────────────────────────────────────
# Email sender (Gmail SMTP)
# ─────────────────────────────────────────────

def send_email(recipient_email: str, subject: str, body: str):
    """
    Sends an email using Gmail SMTP.

    Requires:
      - SENDER_EMAIL
      - SENDER_EMAIL_PASSWORD (Gmail App Password, 16 chars, no spaces)

    Returns:
      - (True, None) on success
      - (False, error_message) on failure
    """
    try:
        sender_email = os.getenv("SENDER_EMAIL")
        sender_password = os.getenv("SENDER_EMAIL_PASSWORD")

        if not sender_email or not sender_password:
            raise ValueError(
                "Missing SENDER_EMAIL or SENDER_EMAIL_PASSWORD. "
                "Ensure environment variables or Streamlit secrets are set."
            )

        msg = EmailMessage()
        msg["From"] = sender_email
        msg["To"] = recipient_email
        msg["Subject"] = subject
        msg.set_content(body)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)

        return True, None

    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────
# Interim advice mapping by issue category
# ─────────────────────────────────────────────

INTERIM_ADVICE_MAP = {
    "Water Seepage": [
        "Exercise caution when accessing the affected area",
        "Avoid placing personal items near the affected location",
        "Do not attempt to rectify the issue independently"
    ],
    "Cleanliness / Pest": [
        "Avoid direct contact with the affected area",
        "Dispose of waste properly where possible",
        "Exercise general caution when nearby"
    ],
    "Infrastructure / Lift": [
        "Avoid using the affected facility if safety is a concern",
        "Follow any posted advisories or signage",
        "Do not attempt repairs on your own"
    ],
    "General": [
        "Exercise caution when accessing the affected area",
        "Avoid attempting to resolve the issue independently",
        "Allow access for inspection where safe to do so"
    ]
}

# ─────────────────────────────────────────────
# Case action update email (Officer → Resident)
# ─────────────────────────────────────────────

def generate_case_action_update_email(
    resident_name: str,
    ref_id: str,
    action_type: str,
    action_notes: str,
    new_status: str,
):
    subject = f"Update on Your Town Council Case ({ref_id})"

    body = f"""
Dear {resident_name or 'Resident'},

We would like to provide you with an update regarding the matter you reported to the Town Council.

✅ Action taken:
{action_type}

📝 Outcome / Details:
{action_notes}

📌 Current case status:
{new_status}

Our officers will continue to monitor the situation and will take further action if required.
If additional information is needed, our team may contact you.

Thank you for your patience and cooperation.

Yours sincerely,
Town Council
Estate Management Team
""".strip()

    return subject, body

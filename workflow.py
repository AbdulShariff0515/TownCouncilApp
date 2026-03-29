# workflow.py
# ------------------------------------------------------------
# Officer Workflow Advisory Engine
# ------------------------------------------------------------
# Provides AI-assisted (or rule-based) recommended actions
# for Town Council officers handling resident feedback.
#
# This module is ADVISORY ONLY.
# Officers remain responsible for final decisions.
# ------------------------------------------------------------

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

import streamlit as st
from dotenv import load_dotenv

# DB access (shared layer)
from db import get_submission_by_ref

# ------------------------------------------------------------
# Environment setup
# ------------------------------------------------------------
load_dotenv()

# ------------------------------------------------------------
# Agency & fallback steps (kept local to avoid tight coupling)
# ------------------------------------------------------------
AGENCY_MAP = {
    "maintenance": "Town Council",
    "cleanliness": "NEA",
    "pests": "NEA / Town Council",
    "parking": "LTA",
    "noise": "Town Council / NEA / SPF",
    "infrastructure": "Town Council / LTA / PUB",
}

FALLBACK_STEPS = {
    "maintenance": [
        "Review issue description and photos",
        "Assign term contractor for inspection",
        "Assess safety risks (electrical / structural)",
        "Update resident after inspection",
    ],
    "cleanliness": [
        "Notify cleaning contractor",
        "Inspect affected area",
        "Schedule cleaning works",
        "Monitor for recurrence",
    ],
    "pests": [
        "Arrange pest inspection",
        "Schedule pest control treatment",
        "Check surrounding areas for breeding",
        "Coordinate with NEA if needed",
    ],
    "parking": [
        "Verify location and jurisdiction",
        "Refer case to enforcement authority",
        "Monitor area for repeat cases",
    ],
    "noise": [
        "Assess timing and nature of disturbance",
        "Determine common area vs private unit",
        "Refer to relevant authority if necessary",
    ],
    "infrastructure": [
        "Confirm asset ownership",
        "Arrange site inspection",
        "Refer or repair accordingly",
    ],
}

# ------------------------------------------------------------
# Public API
# ------------------------------------------------------------
def generate_officer_workflow(ref_id: str) -> Dict:
    """
    Main entry point used by Admin Dashboard.

    Returns a dict with:
    - priority_level
    - recommended_status
    - actions (list)
    - escalate (bool)
    - notes
    """

    case = get_submission_by_ref(ref_id)
    if not case:
        return {
            "error": "Case not found",
            "priority_level": "Unknown",
            "recommended_status": None,
            "actions": [],
            "escalate": False,
            "notes": "Invalid reference ID",
        }

    age_hours = _calculate_case_age_hours(case["created_at"])
    agency = AGENCY_MAP.get(case.get("category"), "Unknown")

    # Attempt AI guidance
    ai_guidance = _ai_officer_guidance(case, age_hours, agency)
    if ai_guidance:
        return ai_guidance

    # Safe rule-based fallback
    return _rule_based_guidance(case, age_hours, agency)


# ------------------------------------------------------------
# AI Guidance (Optional)
# ------------------------------------------------------------
def _ai_officer_guidance(
    case: Dict,
    age_hours: float,
    agency: str,
) -> Optional[Dict]:
    """
    Uses OpenAI to generate officer workflow guidance.
    Returns None on any failure.
    """

    api_key = (
        st.secrets.get("OPENAI_API_KEY")
        if hasattr(st, "secrets")
        else os.getenv("OPENAI_API_KEY")
    )

    if not api_key:
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        
        system_prompt = (
            "You are assisting Singapore Town Council officers.\n"
            "This is advisory decision support ONLY.\n\n"

            "Based on the case details, generate:\n"
            "1. priority_level\n"
            "2. recommended_status\n"
            "3. actions (list of concrete officer steps)\n"
            "4. escalate (true/false)\n"
            "5. notes (short rationale)\n"
            "6. mermaid_diagram (a Mermaid 'flowchart TD' diagram)\n\n"
            
            "Rules for the Mermaid diagram:\n"
            "- Use valid Mermaid flowchart TD syntax only\n"
            "- Node labels MUST be short (2–5 words)\n"
            "- Do NOT use full sentences in node labels\n"
            "- Do NOT use commas, colons, or line breaks in node labels\n"
            "- Use nouns or short verb phrases only\n"
            "- Use decision diamonds sparingly\n"
            "- Do NOT include explanations inside the diagram\n"


            "Return valid JSON only."
        )


        payload = {
            "category": case.get("category"),
            "urgency": case.get("urgency"),
            "current_status": case.get("status"),
            "description": case.get("description"),
            "location": {
                "block": case.get("location_block"),
                "street": case.get("location_street"),
                "details": case.get("location_text"),
            },
            "case_age_hours": round(age_hours, 1),
            "responsible_agency": agency,
        }

        response = client.chat.completions.create(
            model=st.secrets.get("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload)},
            ],
        )

        data = json.loads(response.choices[0].message.content or "{}")

        # Basic validation
        if not isinstance(data.get("actions"), list):
            return None

        return {
            "priority_level": data.get("priority_level", "Normal"),
            "recommended_status": data.get("recommended_status", "In Progress"),
            "actions": data.get("actions", []),
            "escalate": bool(data.get("escalate", False)),
            "notes": data.get("notes", "AI-generated advisory"),
            "mermaid_diagram": data.get("mermaid_diagram"),
        }


    except Exception:
        return None


# ------------------------------------------------------------
# Rule-Based Fallback
# ------------------------------------------------------------
def _rule_based_guidance(
    case: Dict,
    age_hours: float,
    agency: str,
) -> Dict:
    """
    Deterministic fallback logic when AI is unavailable.
    """

    category = case.get("category")
    urgency = case.get("urgency")

    actions = FALLBACK_STEPS.get(
        category,
        ["Review case details and determine next steps"],
    )

    escalate = False
    priority = "Normal"

    if urgency == "Emergency":
        priority = "Critical"
        escalate = True
    elif urgency == "Urgent" or age_hours > 48:
        priority = "High"
        escalate = True

    return {
        "priority_level": priority,
        "recommended_status": "In Progress",
        "actions": actions,
        "escalate": escalate,
        "notes": "Rule-based workflow (AI unavailable)",
        "mermaid_diagram": """
    flowchart TD
        A[Case Received] --> B[Review Case Details]
        B --> C[Assess Safety Risks]
        C --> D{Urgent?}
        D -- Yes --> E[Escalate]
        D -- No --> F[Assign Contractor]
        F --> G[Follow Up]
        E --> G
    """
    }


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def _calculate_case_age_hours(created_at: str) -> float:
    try:
        created = datetime.fromisoformat(created_at)
        return (datetime.now() - created).total_seconds() / 3600
    except Exception:
        return 0.0
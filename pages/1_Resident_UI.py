# -*- coding: utf-8 -*-
"""
Resident Feedback Portal (Town Council) — Single-entry form
Works with admin.py via shared SQLite (data/app.db) provided by db.py

Run:
  streamlit run user_interface_ai.py

Dependencies:
  pip install streamlit python-dotenv openai pandas
"""

from __future__ import annotations

import os
import re
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, List, Tuple

import streamlit as st
from dotenv import load_dotenv

# DB layer (must be in same folder)
from db import init_db, insert_submission, insert_attachment

# ---------------------------------------------------------------
# Basic setup
# ---------------------------------------------------------------
load_dotenv()
st.set_page_config(page_title="Resident Feedback Portal", page_icon="💬", layout="centered")

APP_VERSION = "Resident UI v1.0 — 2026‑03‑25"
st.sidebar.caption(APP_VERSION)

init_db()


# ✅ ADD THIS LINE (exactly once)
submit = False


st.title("💬 Resident Feedback Portal")
st.caption("Submit issues about your estate (maintenance, cleanliness, pests, parking, noise, infrastructure).")

SHOW_CATEGORY_TO_RESIDENT = False

# ---------------------------------------------------------------
# Secret management
# ---------------------------------------------------------------
def get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        if key in st.secrets:
            return st.secrets.get(key, default)
    except Exception:
        pass
    return os.getenv(key, default)

# ---------------------------------------------------------------
# Rules & mappings
# ---------------------------------------------------------------
CATEGORY_PATTERNS: Dict[str, List[str]] = {
    "maintenance": [
        r"\blift (?:not working|break(?:ing)? ?down|stuck|fault(?:y)?|out of service)\b",
        r"\b(leak\w*|seep\w*|drip\w*)\b",
        r"\bspalling concrete\b",
        r"\bpeeling paint\b",
        r"\bbroken (?:rail|railing|bench|lamp|tap|tile|handrail)\b",
        r"\bfaulty (?:light|lamp|switch)\b",
    ],
    "cleanliness": [
        r"\boverflow(?:ing)?\s+bin(?:s)?\b",
        r"\brubbish\b|\btrash\b|\blitter\w*\b",
        r"dirty\s+(corridor|stair(?:case|well)|lift|void deck)\b",
        r"\bchute\b.*\b(?:smell|stink|dirty)\b",
    ],
    "pests": [
        r"\bcockroach\w*\b",
        r"\brodent\w*\b|\brat\w*\b",
        r"\bmosquito\w*\b|\bmidge\w*\b",
        r"\bbed[\s-]?bug\w*\b",
        r"\bpest(?:s)?\b|\bfumigation\b|\blarvae\b",
    ],
    "parking": [
        r"\billegal parking\b",
        r"\bpark\w*.*\b(?:illegal|no parking|double|obstruct\w*)\b",
        r"\bobstruct\w*.*\b(?:driveway|ramp|loading)\b",
        r"\b(?:carpark|lot)\b.*\b(?:issue|problem)\b",
    ],
    "noise": [
        r"\bnois\w*\b|\bloud\w*\b",
        r"\bshout\w*\b|\bparty\w*\b|\b(loud\s+)?music\b",
        r"\bdrill\w*\b|\bhammer\w*\b",
    ],
    "infrastructure": [
        r"\bpothole\w*\b",
        r"\bstreet\s*light(?:s)? (?:not working|out)\b",
        r"\bfoot(?:path|way)\b.*\b(crack\w*|broken\w*)\b",
        r"\bdrain\w*\b.*\b(block(?:ed|age)|chok\w*|clog\w*|silt\w*|flood\w*|pond\w*)\b",
        r"\bdrain\w*\b",
    ],
}

AGENCY_MAP: Dict[str, Dict[str, str]] = {
    "maintenance": {"agency": "Town Council", "notes": "Common property issues (lifts, leaks, lights)."},
    "cleanliness": {"agency": "NEA", "notes": "Cleanliness & hygiene; NEA enforces."},
    "pests": {"agency": "NEA", "notes": "Pest control coordinated by Town Council."},
    "parking": {"agency": "LTA", "notes": "Obstruction/illegal parking on public roads."},
    "noise": {"agency": "Town Council / NEA / SPF", "notes": "Common area vs residential vs late hours."},
    "infrastructure": {"agency": "Town Council / LTA / PUB", "notes": "Roads/drains vs common property."},
}

COMMON_ISSUE_TEMPLATES = {
    "Lift not working": "Lift at Block ___ is not working / stuck between floors.",
    "Water leakage": "Water seeping from ceiling near the corridor / kitchen.",
    "Overflowing bins": "Bins at Block ___ level ___ are overflowing with rubbish.",
    "Rodents seen": "Sighted rats near the bin centre / void deck at night.",
    "Illegal parking": "Vehicle parking illegally and blocking the driveway at ___.",
    "Loud music": "Loud music late at night near ___ affecting residents.",
    "Drain blocked": "Drain along ___ is clogged; water ponding after rain.",
}

# ---------------------------------------------------------------
# Classification (rules + optional OpenAI)
# ---------------------------------------------------------------

def rules_classify(text: str) -> Dict:
    t = (text or "").lower().strip()
    if not t:
        return {"category": None, "confidence": 0.0, "source": "manual"}

    scores = {
        cat: sum(1 for p in patterns if re.search(p, t))
        for cat, patterns in CATEGORY_PATTERNS.items()
    }

    best = max(scores, key=lambda c: scores[c]) if any(scores.values()) else None
    conf = 0.6 + 0.12 * (scores.get(best, 0)) if best else 0.0
    return {
        "category": best,
        "confidence": round(min(conf, 0.95), 2),
        "source": "rules" if best else "manual",
    }


def ai_classify(text: str) -> Optional[Dict]:
    """Optional OpenAI classifier; safe fallback if anything fails."""
    api_key = get_secret("OPENAI_API_KEY")
    if not api_key or not text.strip():
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        model = get_secret("OPENAI_MODEL", "gpt-5.4-mini")

        system_msg = (
            "You classify Singapore Town Council estate issues. "
            "Choose exactly one category from: maintenance, cleanliness, pests, "
            "parking, noise, infrastructure. "
            "Return JSON with keys 'category' and 'confidence'. "
            "Use 'infrastructure' for drains, footpaths, streetlights, roads."
        )

        response = client.chat.completions.create(
            model=model,
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": text.strip()},
            ],
        )

        try:
            data = json.loads(response.choices[0].message.content or "{}")
            cat = str(data.get("category", "")).lower().strip()
            conf = float(data.get("confidence", 0.0))

            if cat in CATEGORY_PATTERNS:
                return {
                    "category": cat,
                    "confidence": round(min(max(conf, 0.0), 1.0), 2),
                    "source": "openai",
                }
        except Exception:
            return None

    except Exception as e:
        st.sidebar.error(f"AI classify error: {e}")
        return None

    return None


def choose_final_classification(text: str) -> Tuple[Optional[str], float, str]:
    """Combines rule‑based and AI classification with safe fallback."""
    r = rules_classify(text)
    a = ai_classify(text)

    if a and (a["confidence"] >= r["confidence"] or r["confidence"] < 0.6):
        return a["category"], a["confidence"], a["source"]

    return r["category"], r["confidence"], r["source"]


# ---------------------------------------------------------------
# ✅ NEW: Town Council next steps (THIS FIXES YOUR CRASH)
# ---------------------------------------------------------------
def council_next_steps(category: Optional[str]) -> List[str]:
    cat = (category or "").lower()

    if cat == "maintenance":
        return [
            "Log case in Town Council maintenance system",
            "Assign term contractor for inspection",
            "Assess safety risks and take immediate action if needed",
            "Update resident once inspection is completed",
        ]

    if cat == "cleanliness":
        return [
            "Notify cleaning contractor",
            "Inspect affected area",
            "Arrange cleaning and disposal works",
            "Monitor for repeat occurrences",
        ]

    if cat == "pests":
        return [
            "Schedule pest inspection",
            "Arrange pest control treatment if required",
            "Inspect surrounding areas for breeding sources",
            "Coordinate with NEA if escalation is needed",
        ]

    if cat == "parking":
        return [
            "Verify location and jurisdiction",
            "Refer case to enforcement authority if applicable",
            "Monitor area for recurring issues",
        ]

    if cat == "noise":
        return [
            "Review reported time and nature of disturbance",
            "Assess whether issue involves common areas or private units",
            "Coordinate with relevant authority if required",
        ]

    if cat == "infrastructure":
        return [
            "Verify asset ownership (Town Council / LTA / PUB)",
            "Arrange site inspection",
            "Schedule repair or refer to responsible agency",
        ]

    return [
        "Review case details",
        "Assign officer for follow-up assessment",
    ]

# ---------------------------------------------------------------
# Local fallback interim advice
# ---------------------------------------------------------------
def local_interim_advice(category: Optional[str]) -> List[str]:
    return [
        "Take photos if safe to do so.",
        "Avoid hazard areas.",
    ]


# ---------------------------------------------------------------
# After submit
# ---------------------------------------------------------------
if submit:
    if not description.strip():
        st.warning("Please describe the issue.")
        st.stop()

    final_category, final_conf, source = choose_final_classification(description)
    ref_id = f"TC-{uuid.uuid4().hex[:8].upper()}"

    insert_submission({
        "ref_id": ref_id,
        "description": description,
        "category": final_category,
        "confidence": final_conf,
        "source": source,
        "status": "New",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })

    #  THIS LINE NOW WORKS
    steps = council_next_steps(final_category)
    tips = local_interim_advice(final_category)

    st.success("Thank you — your feedback has been received.")
    st.markdown(f"**Reference ID:** `{ref_id}`")

    st.subheader("What happens next (Town Council actions)")
    for s in steps:
        st.markdown(f"- {s}")

    st.subheader("What you can do now")
    for t in tips:
        st.markdown(f"- {t}")


# ---------------------------------------------------------------
# Interim advice (AI + fallback)
# ---------------------------------------------------------------

def ai_interim_advice(issue_text: str, category: Optional[str]) -> Optional[List[str]]:
    """Uses OpenAI to generate interim safety advice. Fully safe fallback."""
    api_key = get_secret("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        model = get_secret("OPENAI_MODEL", "gpt-5.4-mini")

        system_msg = (
            "You provide practical, safety-conscious interim advice for residents "
            "reporting estate issues in Singapore (HDB/Town Council). "
            "Return JSON with one key: 'tips' (a list of short bullet points). "
            "Avoid medical or technical diagnoses. Keep tips practical and safe."
        )

        payload = {"message": issue_text, "category": category or "unknown"}

        resp = client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": json.dumps(payload)},
            ],
        )

        try:
            obj = json.loads(resp.choices[0].message.content or "{}")
            tips = obj.get("tips")

            if isinstance(tips, list) and tips:
                return [t.strip() for t in tips if t and t.strip()]

        except Exception:
            return None

    except Exception as e:
        st.sidebar.error(f"AI interim advice error: {e}")
        return None

    return None


# ---------------------------------------------------------------
# Local fallback interim advice
# ---------------------------------------------------------------
def local_interim_advice(category: Optional[str]) -> List[str]:
    cat = (category or "").lower()

    if cat == "maintenance":
        return [
            "Switch off power if water is near electrical points (only if safe).",
            "Contain minor leaks using towels or containers.",
            "Take photos or videos of the issue.",
            "Avoid using the affected equipment until assessed.",
        ]
    if cat == "pests":
        return [
            "Keep food sealed and dispose of waste properly.",
            "Wipe spills promptly to avoid attracting pests.",
            "Take safe photos of sightings or droppings.",
        ]
    if cat == "cleanliness":
        return [
            "Avoid dirty or wet areas to prevent slips.",
            "Secure loose rubbish if manageable.",
            "Share clear photos to help locate the issue.",
        ]
    if cat == "parking":
        return [
            "Avoid confrontation with drivers.",
            "Take note of vehicle number and location safely.",
        ]
    if cat == "noise":
        return [
            "If comfortable, politely inform neighbours.",
            "Record the times the disturbance occurs.",
        ]
    if cat == "infrastructure":
        return [
            "Avoid hazard areas (e.g., broken tiles, potholes).",
            "Maintain a safe distance from exposed parts.",
            "Share clear photos and exact location.",
        ]

    return [
        "Share clear photos and precise location details.",
        "Maintain safe distance if any hazard is present.",
    ]


# ---------------------------------------------------------------
# Sidebar status indicator
# ---------------------------------------------------------------
if get_secret("OPENAI_API_KEY"):
    st.sidebar.success(f"OpenAI: ENABLED  •  Model: {get_secret('OPENAI_MODEL', 'gpt-5.4-mini')}")
else:
    st.sidebar.warning("OpenAI: disabled (rules‑only fallback)")

# ---------------------------------------------------------------
# UI — Single-entry resident form
# ---------------------------------------------------------------
st.subheader("Share your feedback")

# Location inputs
col_loc1, col_loc2 = st.columns(2)
blocks = ["(Select)", "Block 101", "Block 102", "Block 201", "Block 202", "Other"]
streets = ["(Select)", "Pasir Ris Dr 1", "Pasir Ris Dr 3", "Elias Rd", "Loyang Ave", "Other"]

selected_block = col_loc1.selectbox("Block (optional)", options=blocks, index=0)
selected_street = col_loc2.selectbox("Street (optional)", options=streets, index=0)
location_text = st.text_input("Location details (optional)",
    placeholder="E.g., Stairwell between levels 8–9, near lift lobby A")

colA, colB = st.columns(2)
name = colA.text_input("Your name (optional)")
contact = colB.text_input("Contact (email or phone, optional)")

# Templates
with st.expander("Quick fill suggestions (optional)"):
    tmpl = st.selectbox("Pick a common issue to prefill:",
                        ["(None)"] + list(COMMON_ISSUE_TEMPLATES.keys()))
    if st.button("Insert template", use_container_width=True, disabled=(tmpl == "(None)")):
        st.session_state["desc_prefill"] = COMMON_ISSUE_TEMPLATES.get(tmpl, "")

description = st.text_area(
    "Describe the issue",
    value=st.session_state.get("desc_prefill", ""),
    height=140,
    placeholder="E.g., Water seeping from my ceiling near the corridor.",
)

urgency = st.selectbox("How urgent is this?", ["Normal", "Urgent", "Emergency"], index=0)
consent = st.checkbox("I consent to being contacted about this feedback.")

# Photo uploads
uploads = st.file_uploader(
    "Add photos (optional)",
    type=["png", "jpg", "jpeg", "heic", "webp"],
    accept_multiple_files=True,
)

submit = st.button("Submit", type="primary", use_container_width=True)


# ---------------------------------------------------------------
# After submit
# ---------------------------------------------------------------
if submit:
    if not description.strip():
        st.warning("Please describe the issue so we can assist.")
        st.stop()

    # Hybrid classification
    final_category, final_conf, source = choose_final_classification(description)
    agency_info = AGENCY_MAP.get(final_category)

    # Generate reference ID
    ref_id = (
        f"TC-{datetime.now().strftime('%Y%m%d-%H%M%S')}-"
        f"{str(uuid.uuid4())[:8].upper()}"
    )

    # Record for DB
    record = {
        "ref_id": ref_id,
        "name": name.strip() or None,
        "contact": contact.strip() or None,
        "consent": 1 if consent else 0,
        "location_text": location_text.strip() or None,
        "location_block": None if selected_block in ("(Select)", "Other") else selected_block,
        "location_street": None if selected_street in ("(Select)", "Other") else selected_street,
        "urgency": urgency,
        "description": description.strip(),
        "category": final_category,
        "confidence": float(final_conf or 0.0),
        "source": source,
        "status": "New",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    insert_submission(record)

    # Save uploads
    os.makedirs(os.path.join("data", "uploads"), exist_ok=True)
    for up in uploads or []:
        safe_filename = f"{ref_id}_{re.sub(r'[^A-Za-z0-9_.-]+', '-', up.name)}"
        stored_path = os.path.join("data", "uploads", safe_filename)

        with open(stored_path, "wb") as f:
            f.write(up.getbuffer())

        insert_attachment(
            ref_id=ref_id,
            filename=up.name,
            stored_path=stored_path,
            mime_type=getattr(up, "type", None),
            created_at=datetime.now().isoformat(timespec="seconds"),
        )

    # Generate advice
    steps = council_next_steps(final_category)
    ai_tips = ai_interim_advice(description, final_category)
    tips = ai_tips or local_interim_advice(final_category)

    # -----------------------------------------------------------
    # Output to user
    # -----------------------------------------------------------
    st.success("Thank you — your feedback has been received.")
    st.markdown(f"**Reference ID:** `{ref_id}`")
    st.write("An officer will be in touch with you regarding your feedback.")

    if SHOW_CATEGORY_TO_RESIDENT and final_category:
        st.markdown(
            f"**Detected category:** **{final_category}** "
            f"(confidence: {final_conf})"
        )

    if agency_info:
        st.markdown(f"**Suggested agency:** {agency_info['agency']}")
        if agency_info.get("notes"):
            st.caption(agency_info["notes"])

    st.divider()
    st.subheader("What happens next (Town Council actions)")
    for s in steps:
        st.markdown(f"- {s}")

    st.subheader("What you can do now (optional)")
    for t in tips:
        st.markdown(f"- {t}")

    st.info(
        "If anyone is in immediate danger (e.g., fire, flooding, electrocution risk),"
        " keep a safe distance and contact emergency services."
    )


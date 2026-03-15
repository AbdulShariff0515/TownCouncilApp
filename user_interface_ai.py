# -*- coding: utf-8 -*-
"""
Resident Feedback Portal (Town Council) — Single-entry form (Standalone)

Resident flow:
  1) Resident sees ONLY one form: "Share your feedback".
  2) On Submit: background classification runs; page shows:
       - Acknowledgement + Reference ID
       - What happens next (what the Town Council will do)
       - What you can do now (optional) — OpenAI-backed tips if configured; else safe local tips
  3) No second textbox; no "Classify" UI anywhere.

This file is self-contained (does NOT import classifier.py) to avoid UI conflicts.

Setup (once):
  pip install streamlit python-dotenv openai
Optional .env (same folder):
  OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
  OPENAI_MODEL=gpt-4o-mini

Run:
  python -m streamlit run user_interface_ai.py
"""

import os
import re
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, List

import streamlit as st
from dotenv import load_dotenv

# ---------------------------
# Page setup (must be early)
# ---------------------------
load_dotenv()
st.set_page_config(page_title="Resident Feedback Portal", page_icon="💬", layout="centered")

st.title("💬 Resident Feedback Portal")

# Toggle to show detected category/confidence to residents (set False to hide)
SHOW_CATEGORY_TO_RESIDENT = False

# ---------------------------
# Simple built-in classifier (rules)
# ---------------------------
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
    "cleanliness": {"agency": "NEA", "notes": "Cleanliness & hygiene. Town Council handles ops; NEA enforces."},
    "pests": {"agency": "NEA", "notes": "Pest control for common areas coordinated by Town Council."},
    "parking": {"agency": "LTA", "notes": "Obstruction/illegal parking on public roads."},
    "noise": {"agency": "Town Council / NEA / SPF", "notes": "Common area noise → Town Council; late hours → SPF/NEA."},
    "infrastructure": {"agency": "Town Council / LTA / PUB", "notes": "Estate fixtures → Town Council; roads/drains → LTA/PUB."},
}

def simple_classify(text: str) -> Dict:
    """
    Returns:
      {
        "final_category": str|None,
        "final_confidence": float,
        "confidence_label": "High|Medium|Low",
        "source": "rules"|"manual",
        "agency": {...}|None
      }
    """
    t = (text or "").lower().strip()
    if not t:
        return {
            "final_category": None,
            "final_confidence": 0.0,
            "confidence_label": "Low",
            "source": "manual",
            "agency": None,
        }
    scores = {cat: sum(1 for p in pats if re.search(p, t)) for cat, pats in CATEGORY_PATTERNS.items()}
    best = max(scores, key=lambda c: scores[c]) if any(scores.values()) else None
    conf = 0.6 + 0.12 * (scores.get(best, 0)) if best else 0.0
    conf = min(0.95, conf)
    label = "High" if conf >= 0.8 else ("Medium" if conf >= 0.5 else "Low")
    agency = AGENCY_MAP.get(best) if best else None
    return {
        "final_category": best,
        "final_confidence": round(conf, 2),
        "confidence_label": label,
        "source": "rules" if best else "manual",
        "agency": agency,
    }

# ---------------------------
# Helpers: reference, saving, steps & advice
# ---------------------------
def generate_ref() -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"TC-{ts}-{str(uuid.uuid4())[:8].upper()}"

def save_submission(payload: dict, save: bool = True) -> None:
    """Append to data/submissions.jsonl locally. Create folder if needed."""
    if not save:
        return
    try:
        os.makedirs("data", exist_ok=True)
        path = os.path.join("data", "submissions.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # Do not break resident flow if persistence fails
        pass

def council_next_steps(category: Optional[str]) -> List[str]:
    """
    What the Town Council will do next (We will …).
    Always includes: An officer will be in touch with you regarding your feedback.
    """
    contact_line = "An officer will be in touch with you regarding your feedback."
    cat = (category or "").lower()

    if cat == "maintenance":
        steps = [
            "We will log your case and notify our maintenance team.",
            "We will arrange an inspection of the affected area.",
            "We will coordinate repairs with the relevant contractor/HDB where applicable.",
            "We will keep you updated on progress and estimated timelines.",
        ]
    elif cat == "cleanliness":
        steps = [
            "We will inform our cleaning supervisor to dispatch a crew.",
            "We will inspect the location and address the cleanliness issue.",
            "We will monitor the area over the next few days for recurrence.",
        ]
    elif cat == "pests":
        steps = [
            "We will alert our pest control contractor to assess the situation.",
            "We will arrange targeted treatment in the affected common areas.",
            "We will monitor for recurrence and schedule follow‑up treatments if needed.",
        ]
    elif cat == "parking":
        steps = [
            "We will record the details and forward them to the relevant enforcement authority as needed.",
            "We will conduct site checks (if within estate premises).",
            "We will coordinate with the authorities where required.",
        ]
    elif cat == "noise":
        steps = [
            "We will record your feedback including location and time window.",
            "If in common areas, we will schedule checks by our officers.",
            "For persistent residential noise, we will advise mediation or refer to relevant authorities as appropriate.",
        ]
    elif cat == "infrastructure":
        steps = [
            "We will log the structural issue for inspection by our technical team.",
            "We will schedule remediation or escalate to the relevant agency (e.g., roads/drains).",
            "We will provide an estimated timeline once assessed.",
        ]
    else:
        steps = [
            "We will create a case in our system and review your feedback.",
            "We will route your case to the appropriate team or partner agency.",
            "We will update you once a plan and timeline are confirmed.",
        ]

    steps.append(contact_line)
    return steps

def local_interim_advice(category: Optional[str]) -> List[str]:
    """Resident actions (fallback if OpenAI is not configured)."""
    cat = (category or "").lower()
    if cat == "maintenance":
        return [
            "If water is near electrical points and it is safe to do so, switch off power to the affected area.",
            "Use a container or towels to contain minor leakage and protect valuables.",
            "Take clear photos/videos of the issue and note when it occurs.",
            "Avoid using the affected fixture (e.g., tap/shower) until assessed.",
        ]
    if cat == "pests":
        return [
            "Keep food covered and dispose garbage in sealed bags.",
            "Wipe spills and crumbs promptly; avoid leaving pet food out.",
            "If safe, take photos of sightings and possible entry points.",
            "Avoid strong chemicals that may disperse pests—targeted treatment is preferable.",
        ]
    if cat == "cleanliness":
        return [
            "Avoid the dirty or wet area to prevent slips.",
            "If manageable, secure loose trash to reduce odours.",
            "Share photos to help us identify exact spots.",
        ]
    if cat == "parking":
        return [
            "Do not engage directly if confrontation risk is present.",
            "If safe, note the vehicle number, location, and time.",
            "Keep access ways clear for emergency vehicles.",
        ]
    if cat == "noise":
        return [
            "If comfortable and safe, politely inform neighbours of the disturbance.",
            "Use earplugs or white noise as a temporary measure.",
            "Record times of disturbance to aid follow‑up.",
        ]
    if cat == "infrastructure":
        return [
            "Avoid the affected area if there is a trip or fall hazard.",
            "Keep a safe distance from sharp edges or exposed parts.",
            "Share clear photos and the exact location.",
        ]
    return [
        "Share clear photos/videos and precise location details.",
        "Keep a safe distance if there is any immediate danger.",
        "We will update you after initial assessment.",
    ]

def ai_interim_advice(issue_text: str, category: Optional[str]) -> Optional[List[str]]:
    """Use OpenAI (if configured) to produce resident-safe interim advice."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        system_msg = (
            "You are a safety-conscious assistant for residents reporting estate issues in Singapore (HDB/Town Council). "
            "Given the resident's message and detected category, provide practical interim steps the resident can take now. "
            "Keep advice specific, actionable, and safe; avoid professional diagnoses. "
            "Use at most 5 concise bullet points. If there is immediate danger, include a first bullet on safety. "
            "Return JSON with key 'tips' as a list of strings."
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
        data = resp.choices[0].message.content
        obj = json.loads(data)
        tips = obj.get("tips")
        if isinstance(tips, list) and tips:
            return [str(t).strip() for t in tips if str(t).strip()]
        return None
    except Exception:
        return None

# ---------------------------
# UI — Single entry form
# ---------------------------
with st.form("resident_form", clear_on_submit=False):
    st.subheader("Share your feedback")
    col1, col2 = st.columns(2)
    name = col1.text_input("Your name (optional)")
    contact = col2.text_input("Contact (email or phone, optional)")
    location = st.text_input("Location (e.g., Block, Street, Unit — optional)")
    description = st.text_area(
        "Describe the issue",
        height=140,
        placeholder="E.g., Water seeping from my ceiling near the corridor.",
    )
    urgency = st.selectbox("How urgent is this?", ["Normal", "Urgent", "Emergency"], index=0)
    consent = st.checkbox("I consent to being contacted about this feedback.")
    submit = st.form_submit_button("Submit", type="primary")

# ---------------------------
# After submit: acknowledgement + next steps
# ---------------------------
if submit:
    if not description.strip():
        st.warning("Please describe the issue so we can assist.")
        st.stop()

    # Background classification (rules only, no visible UI)
    result = simple_classify(description)
    category = result.get("final_category")
    confidence = result.get("final_confidence", 0.0)
    agency_info = AGENCY_MAP.get(category) if category else None

    # Create reference & store
    ref_id = generate_ref()
    record = {
        "ref_id": ref_id,
        "name": (name or "").strip() or None,
        "contact": (contact or "").strip() or None,
        "consent": bool(consent),
        "location": (location or "").strip() or None,
        "urgency": urgency,
        "description": (description or "").strip(),
        "category": category,
        "confidence": confidence,
        "source": result.get("source"),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    save_submission(record, save=True)

    # Outputs
    council_steps = council_next_steps(category)
    tips = ai_interim_advice(description, category) or local_interim_advice(category)

    # Acknowledgement & summary
    st.success("Thank you — your feedback has been received.")
    st.markdown(f"**Reference ID:** `{ref_id}`")
    st.write("An officer will be in touch with you regarding your feedback.")

    if SHOW_CATEGORY_TO_RESIDENT and category:
        color = "green" if confidence >= 0.8 else ("orange" if confidence >= 0.5 else "gray")
        st.markdown(f"**Detected category:** :{color}[{category}]  (confidence: {confidence})")

    if agency_info:
        st.markdown(f"**Suggested agency:** {agency_info['agency']}")
        notes = agency_info.get("notes", "")
        if notes:
            st.caption(notes)

    st.divider()
    st.subheader("What happens next (what the Town Council will do)")
    for s in council_steps:
        st.markdown(f"- {s}")

    st.subheader("What you can do now (optional)")
    for t in tips:
        st.markdown(f"- {t}")

    st.info("If anyone is in immediate danger (e.g., electrocution/flood risk), keep a safe distance and contact emergency services.")
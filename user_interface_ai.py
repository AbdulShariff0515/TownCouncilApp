# -*- coding: utf-8 -*-
"""
Resident Feedback Portal (Town Council) — Single-entry form
Works with admin.py via shared SQLite (data/app.db) provided by db.py

Run:
  python -m streamlit run user_interface_ai.py

Deps:
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

# --- Shared DB layer (db.py must be in the SAME folder) ---
from db import init_db, insert_submission, insert_attachment


# ------------------------------------------------------------------------------
# Basic setup
# ------------------------------------------------------------------------------
load_dotenv()
st.set_page_config(page_title="Resident Feedback Portal", page_icon="💬", layout="centered")

APP_VERSION = "Resident UI v0.4 — DB+uploads — 2026‑03‑22"
st.sidebar.caption(APP_VERSION)

# Initialize DB tables (idempotent)
init_db()

st.title("💬 Resident Feedback Portal")
st.caption("Submit issues about your estate (maintenance, cleanliness, pests, parking, noise, infrastructure).")

# Show detected category to resident?
SHOW_CATEGORY_TO_RESIDENT = False


# ------------------------------------------------------------------------------
# Helpers for secrets (works locally & on Streamlit Cloud)
# ------------------------------------------------------------------------------
def get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    # Cloud: st.secrets ; Local: os.environ/.env
    try:
        if key in st.secrets:
            return st.secrets.get(key, default)
    except Exception:
        pass
    return os.getenv(key, default)


# ------------------------------------------------------------------------------
# Rules & mappings
# ------------------------------------------------------------------------------
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

COMMON_ISSUE_TEMPLATES = {
    "Lift not working": "Lift at Block ___ is not working / stuck between floors.",
    "Water leakage": "Water seeping from ceiling near the corridor / kitchen.",
    "Overflowing bins": "Bins at Block ___ level ___ are overflowing with rubbish.",
    "Rodents seen": "Sighted rats near the bin centre / void deck at night.",
    "Illegal parking": "Vehicle parking illegally and blocking the driveway at ___.",
    "Loud music": "Loud music late at night near ___ affecting residents.",
    "Drain blocked": "Drain along ___ is clogged; water ponding after rain.",
}


# ------------------------------------------------------------------------------
# Classification (rules + optional OpenAI) — fully guarded
# ------------------------------------------------------------------------------
def rules_classify(text: str) -> Dict:
    t = (text or "").lower().strip()
    if not t:
        return {"category": None, "confidence": 0.0, "source": "manual"}
    scores = {cat: sum(1 for p in pats if re.search(p, t)) for cat, pats in CATEGORY_PATTERNS.items()}
    best = max(scores, key=lambda c: scores[c]) if any(scores.values()) else None
    conf = 0.6 + 0.12 * (scores.get(best, 0)) if best else 0.0
    conf = min(0.95, conf)
    return {"category": best, "confidence": round(conf, 2), "source": "rules" if best else "manual"}


def ai_classify(text: str) -> Optional[Dict]:
    """Optional OpenAI classifier. Safe to leave as-is; returns None if key/module missing or any error occurs."""
    api_key = get_secret("OPENAI_API_KEY")
    if not api_key or not text.strip():
        return None
    try:
        # Import inside try so missing package never crashes the app
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=api_key)
        model = get_secret("OPENAI_MODEL", "gpt-4o-mini")
        system_msg = (
            "You are a classification assistant for Singapore Town Council estate issues. "
            "Choose exactly one category from: maintenance, cleanliness, pests, parking, noise, infrastructure. "
            "Return JSON: {\"category\": <one_of_list>, \"confidence\": 0.0-1.0}. "
            "Use 'infrastructure' for roads/footpaths/drains/streetlights."
        )
        resp = client.chat.completions.create(
            model=model,
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": text.strip()},
            ],
        )
        try:
            data = json.loads(resp.choices[0].message.content or "{}")
            cat = str(data.get("category", "")).strip().lower()
            conf = float(data.get("confidence", 0.0))
            if cat in CATEGORY_PATTERNS:
                return {"category": cat, "confidence": round(min(max(conf, 0.0), 1.0), 2), "source": "openai"}
        except Exception:
            return None
    except Exception:
        return None
    return None


def choose_final_classification(text: str) -> Tuple[Optional[str], float, str]:
    r = rules_classify(text)
    a = ai_classify(text)
    if a and (a["confidence"] >= r["confidence"] or r["confidence"] < 0.6):
        return a["category"], a["confidence"], a["source"]
    return r["category"], r["confidence"], r["source"]


# ------------------------------------------------------------------------------
# Next steps & advice (OpenAI advice optional, fully guarded)
# ------------------------------------------------------------------------------
def council_next_steps(category: Optional[str]) -> List[str]:
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
    cat = (category or "").lower()
    if cat == "maintenance":
        return [
            "If water is near electrical points and it is safe to do so, switch off power to the affected area.",
            "Use towels/containers to contain minor leakage; protect valuables.",
            "Take clear photos/videos of the issue and note when it occurs.",
            "Avoid using the affected fixture until assessed.",
        ]
    if cat == "pests":
        return [
            "Keep food covered and dispose garbage in sealed bags.",
            "Wipe spills promptly; avoid leaving pet food out.",
            "If safe, take photos of sightings and entry points.",
            "Avoid strong chemicals that may disperse pests; targeted treatment is preferable.",
        ]
    if cat == "cleanliness":
        return [
            "Avoid the dirty/wet area to prevent slips.",
            "Secure loose trash if manageable.",
            "Share photos to help locate exact spots.",
        ]
    if cat == "parking":
        return [
            "Do not engage directly if confrontation risk is present.",
            "If safe, note vehicle number, location, and time.",
            "Keep access ways clear.",
        ]
    if cat == "noise":
        return [
            "If comfortable and safe, politely inform neighbours.",
            "Use earplugs/white noise temporarily.",
            "Record times of disturbance.",
        ]
    if cat == "infrastructure":
        return [
            "Avoid the affected area if there is a hazard.",
            "Keep a safe distance from exposed parts.",
            "Share clear photos and the exact location.",
        ]
    return [
        "Share clear photos/videos and precise location details.",
        "Keep a safe distance if there is any danger.",
        "We will update you after initial assessment.",
    ]


def ai_interim_advice(issue_text: str, category: Optional[str]) -> Optional[List[str]]:
    api_key = get_secret("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=api_key)
        model = get_secret("OPENAI_MODEL", "gpt-4o-mini")
        system_msg = (
            "You are a safety-conscious assistant for residents reporting estate issues in Singapore (HDB/Town Council). "
            "Given the resident's message and detected category, provide practical interim steps. "
            "Keep advice specific, actionable, and safe; avoid professional diagnoses. "
            "Use at most 5 concise bullet points. If immediate danger exists, include a safety note first. "
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
        try:
            obj = json.loads(resp.choices[0].message.content or "{}")
            tips = obj.get("tips")
            if isinstance(tips, list) and tips:
                return [str(t).strip() for t in tips if str(t).strip()]
        except Exception:
            return None
    except Exception:
        return None
    return None


# ------------------------------------------------------------------------------
# Sidebar status (so you can confirm environment)
# ------------------------------------------------------------------------------
if get_secret("OPENAI_API_KEY"):
    st.sidebar.success(f"OpenAI: ENABLED  •  Model: {get_secret('OPENAI_MODEL', 'gpt-4o-mini')}")
else:
    st.sidebar.warning("OpenAI: disabled (rules-only fallback)")


# ------------------------------------------------------------------------------
# UI — Single-entry resident form
# ------------------------------------------------------------------------------
st.subheader("Share your feedback")

# Location inputs
col_loc1, col_loc2 = st.columns(2)
blocks = ["(Select)", "Block 101", "Block 102", "Block 201", "Block 202", "Other"]
streets = ["(Select)", "Pasir Ris Dr 1", "Pasir Ris Dr 3", "Elias Rd", "Loyang Ave", "Other"]

selected_block = col_loc1.selectbox("Block (optional)", options=blocks, index=0)
selected_street = col_loc2.selectbox("Street (optional)", options=streets, index=0)
location_text = st.text_input("Location details (optional)", placeholder="E.g., Stairwell between levels 8–9, near lift lobby A")

colA, colB = st.columns(2)
name = colA.text_input("Your name (optional)")
contact = colB.text_input("Contact (email or phone, optional)")

# Quick templates
with st.expander("Quick fill suggestions (optional)"):
    tmpl = st.selectbox("Pick a common issue to prefill:", ["(None)"] + list(COMMON_ISSUE_TEMPLATES.keys()), index=0)
    if st.button("Insert template", use_container_width=True, disabled=(tmpl == "(None)")):
        st.session_state["desc_prefill"] = COMMON_ISSUE_TEMPLATES.get(tmpl, "")

description = st.text_area(
    "Describe the issue",
    height=140,
    value=st.session_state.get("desc_prefill", ""),
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


# ------------------------------------------------------------------------------
# After submit
# ------------------------------------------------------------------------------
if submit:
    if not (description or "").strip():
        st.warning("Please describe the issue so we can assist.")
        st.stop()

    # Hybrid classification with safe fallback
    final_category, final_conf, source = choose_final_classification(description)
    agency_info = AGENCY_MAP.get(final_category) if final_category else None

    # Create reference & record
    ref_id = f"TC-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{str(uuid.uuid4())[:8].upper()}"
    record = {
        "ref_id": ref_id,
        "name": (name or "").strip() or None,
        "contact": (contact or "").strip() or None,
        "consent": 1 if consent else 0,
        "location_text": (location_text or "").strip() or None,
        "location_block": None if selected_block in ("(Select)", "Other") else selected_block,
        "location_street": None if selected_street in ("(Select)", "Other") else selected_street,
        "urgency": urgency,
        "description": (description or "").strip(),
        "category": final_category,
        "confidence": float(final_conf or 0.0),
        "source": source,  # "rules" | "openai" | "manual"
        "status": "New",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    insert_submission(record)

    # Save uploads & register in DB
    os.makedirs(os.path.join("data", "uploads"), exist_ok=True)
    for up in uploads or []:
        safe_fn = f"{ref_id}_{re.sub(r'[^A-Za-z0-9_.-]+', '-', up.name)}"
        stored_path = os.path.join("data", "uploads", safe_fn)
        with open(stored_path, "wb") as f:
            f.write(up.getbuffer())
        insert_attachment(
            ref_id=ref_id,
            filename=up.name,
            stored_path=stored_path,
            mime_type=getattr(up, "type", None),
            created_at=datetime.now().isoformat(timespec="seconds"),
        )

    # Outputs
    steps = council_next_steps(final_category)
    tips = ai_interim_advice(description, final_category) or local_interim_advice(final_category)

    st.success("Thank you — your feedback has been received.")
    st.markdown(f"**Reference ID:** `{ref_id}`")
    st.write("An officer will be in touch with you regarding your feedback.")

    if SHOW_CATEGORY_TO_RESIDENT and final_category:
        color = "green" if final_conf >= 0.8 else ("orange" if final_conf >= 0.5 else "gray")
        st.markdown(f"**Detected category:** :{color}[{final_category}] (confidence: {final_conf})")

    if agency_info:
        st.markdown(f"**Suggested agency:** {agency_info['agency']}")
        if agency_info.get("notes"):
            st.caption(agency_info["notes"])

    st.divider()
    st.subheader("What happens next (what the Town Council will do)")
    for s in steps:
        st.markdown(f"- {s}")

    st.subheader("What you can do now (optional)")
    for t in tips:
        st.markdown(f"- {t}")

    st.info("If anyone is in immediate danger (e.g., electrocution/flood risk), keep a safe distance and contact emergency services.")

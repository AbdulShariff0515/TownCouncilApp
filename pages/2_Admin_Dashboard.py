# admin_app.py

# ── Standard library ─────────────────────────────
import os
import re
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, List



# ── Third-party ──────────────────────────────────
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

# ── Local modules ─────────────────────────────────
from components.case_timeline import render_case_timeline
from ai_classification import classify_issue_ai
from workflow import generate_officer_workflow
from db import (
    init_db,
    list_submissions,
    get_attachments,
    update_status,
    update_case_category,
    log_workflow_decision,
    list_progress_entries,
    create_progress_entry,
    save_case_action_and_notify as save_case_action,

    # ✅ Phase 1 adapters
    get_case_by_reference_id,
    get_officer_notes,
    save_officer_notes,
    save_case_action_and_notify as save_case_action,
    get_case_actions,
)

# ── Streamlit page config (MUST be after st import) ─
st.set_page_config(
    page_title="Town Council – Staff Dashboard",
    page_icon="🗂️",
    layout="wide"
)

# ── App initialisation ───────────────────────────
load_dotenv()
init_db()


# ── Session state initialisation ─────────────────
if "ai_classified_case_id" not in st.session_state:
    st.session_state.ai_classified_case_id = None

if "ai_classification" not in st.session_state:
    st.session_state.ai_classification = None

if "ai_logged_to_timeline" not in st.session_state:
    st.session_state.ai_logged_to_timeline = False

if "ai_suggested_category" not in st.session_state:
    st.session_state.ai_suggested_category = None

if "ai_override_logged" not in st.session_state:
    st.session_state.ai_override_logged = False

# ── App UI ────────────────────────────────────────

# ------------------------------------------------------------
# 🔐 Admin password gate (MUST be first UI element)
# ------------------------------------------------------------
if "auth" not in st.session_state:
    st.session_state.auth = False

st.title("🔐 Town Council Admin Access")

if not st.session_state.auth:
    pwd = st.text_input("Enter admin password", type="password")

    if pwd:
        if pwd == os.getenv("ADMIN_PASSWORD", "admin"):
            st.session_state.auth = True
            st.rerun()  # ✅ THIS IS THE FIX
        else:
            st.error("❌ Incorrect password")

    st.info("Please enter the admin password to continue.")
    st.stop()

# ============================================================
# HELPER FUNCTIONS (ALWAYS ABOVE UI)
# ============================================================

# ✅ Allowed officer actions for Actions Taken timeline
OFFICER_ACTION_TYPES = {
    "Site Inspection",
    "Relevant Agency Consulted",
    "Phone Call to Resident",
    "Letter Issued to Resident",
    "Contractor Engaged",
    "Follow-up Visit",
    "Internal Review",
    "Resident Feedback",
    "Case Closed",
    "Other"
}

def build_visual_case_timeline(ref_id: str):
    entries = list_progress_entries(ref_id)

    timeline = []
    current_status = "New"

    for entry in entries:
        timeline.append({
            "status": entry["step_code"],
            "label": entry["step_label"],
            "created_at": entry["created_at"],
            "ai_override": entry["step_code"] == "AI_OVERRIDE",
        })

        if entry["step_code"] == "STATUS_UPDATED":
            current_status = entry["step_label"].replace(
                "Status updated to ", ""
            )

    return timeline, current_status


def render_case_progress(ref_id: str):
    st.subheader("Case Progress")

    entries = list_progress_entries(ref_id)

    if not entries:
        st.caption("No progress updates recorded yet.")
        return

    for entry in entries:
        col_icon, col_body = st.columns([1, 10])

        with col_icon:
            st.markdown("✅")

        with col_body:
            st.markdown(f"**{entry['step_label']}**")
            st.caption(entry["created_at"])

            if entry.get("notes"):
                st.markdown(
                    f"<span style='color:#6c757d'>{entry['notes']}</span>",
                    unsafe_allow_html=True
                )

        st.divider()


# OFFICER timeline (new)
def build_officer_action_timeline(case_id: str):
    actions = get_case_actions(case_id) or []

    actions = sorted(
        actions,
        key=lambda a: a["created_at"]
    )

    timeline = []
    
    for action in actions:
        if action["action_type"] not in OFFICER_ACTION_TYPES:
            continue  # 🚫 exclude AI / admin / system actions

        timeline.append({
            
            "status": "OFFICER_ACTION",
            "label": action["action_type"],
            "created_at": action["created_at"],
            "notes": action.get("action_notes"),
            "actor": "Officer"

        })

    return timeline


# ------------------------------------------------------------
# ✅ Dashboard starts here (only after login)
# ------------------------------------------------------------

st.title("Town Council Admin")

# ✅ Initialise session state
if "case" not in st.session_state:
    st.session_state.case = None

# ✅ Always read case FIRST
case = st.session_state.case

# ✅ Show hint only when no case is loaded
if not case:
    st.info("Enter a reference ID above to open a case.")

st.subheader("Open case by Reference ID")

ref_id = st.text_input(
    "Reference ID",
    placeholder="TC-YYYYMMDD-XXXXXX-XXXX"
)

open_case = st.button("Open Case")

if open_case and ref_id:
    result = get_case_by_reference_id(ref_id)

    if not result:
        st.error("❌ Case not found. Please check the reference ID.")
        st.session_state.case = None
        case = None
    else:
        st.session_state.case = result
        case = result  # ✅ keep local variable in sync
        
        # ✅ Reset AI state for newly opened case
        st.session_state.ai_classified_case_id = None
        st.session_state.ai_logged_to_timeline = False
        st.session_state.ai_classification = None
   
if case:
    # ─────────────────────────────────────
    # 📄 Case Header
    # ─────────────────────────────────────
    st.markdown(f"## Case: {case['ref_id']}")

    issue_description = case.get("description", "")

    # ─────────────────────────────────────
    # 🧾 Resident Issue (Read-only)
    # ─────────────────────────────────────
    st.subheader("Issue Description from Resident")
    st.text_area(
        label="Resident-submitted description",
        value=issue_description,
        height=180,
        disabled=True
    )
    st.caption("🛡️ This is the original description submitted by the resident and cannot be edited.")

    st.divider()

    # ─────────────────────────────────────
    # 🤖 AI Classification (Suggested)
    # ─────────────────────────────────────
    st.subheader("🧠 AI Classification (Suggested)")

    st.info(
        "The AI assessment below is based on the resident description shown above."
    )

    # ✅ Run AI only once per case (only when status is New)
    if case.get("status") == "New":
        if st.session_state.ai_classified_case_id != case["ref_id"]:
            with st.spinner("Classifying issue using AI..."):
                try:
                    ai_result = classify_issue_ai(
                        description=issue_description,
                        location=case.get("location", "")
                    )

                    # ✅ Persist AI result
                    st.session_state.ai_classification = ai_result
                    st.session_state.ai_classified_case_id = case["ref_id"]
                    st.session_state.ai_suggested_category = ai_result.get("category")

                    # ✅ Log AI classification to timeline once
                    if not st.session_state.ai_logged_to_timeline:
                        create_progress_entry(
                            ref_id=case["ref_id"],
                            step_code="AI_CLASSIFICATION",
                            step_label="AI classification completed",
                            notes=(
                                f"AI classified issue as "
                                f"{ai_result.get('category', 'Unknown')} "
                                f"({ai_result.get('confidence', 0):.0%} confidence)"
                            )
                        )

                        st.session_state.ai_logged_to_timeline = True

                except Exception as e:
                    st.error(f"AI classification failed: {e}")
    else:
        st.info("🔒 AI classification locked after officer action")

    # ✅ Display AI result (read-only)
    if st.session_state.ai_classification:
        ai = st.session_state.ai_classification

        st.markdown("### 🧠 AI Classification Result")
        st.write("**Category:**", ai.get("category", "-"))
        st.write("**Sub-category:**", ai.get("sub_category", "-"))
        st.write("**Priority:**", ai.get("priority", "-"))
        st.write("**Severity:**", ai.get("severity", "-"))
        st.write("**Handling Unit:**", ai.get("handling_unit", "-"))
        st.write("**Confidence:**", f"{ai.get('confidence', 0):.0%}")

        if ai.get("confidence", 0) < 0.6:
            st.warning("⚠️ Low confidence — officer review recommended")

    st.divider()

    # ───────────────────────────────────
    # 🧑‍💼 Officer Action (Category Decision)
    # ─────────────────────────────────────
    
    st.subheader("Officer Action")

    selected_category = st.selectbox(
        "Confirm / Update Case Category",
        [
            "Plumbing",
            "Electrical",
            "Pest Control",
            "Cleaning",

            "Structural",
            "Others"
        ])

    if st.button("Save Case Action"):

        # 1️⃣ Persist the category change
        update_case_category(
                case_id=case["ref_id"],
                category=selected_category,
                updated_by="ADMIN"
        )

        # 2️⃣ Log category confirmation (progress / audit only)
        create_progress_entry(
            ref_id=case["ref_id"],
                step_code="CATEGORY_CONFIRMED",
                step_label="Category confirmed by officer",
            notes=f"Category set to {selected_category}"
        )

        # 3️⃣ AI override detection
        ai_category = st.session_state.get("ai_suggested_category")

        if (
            ai_category
            and selected_category != ai_category
            and not st.session_state.get("ai_override_logged")
        ):
            create_progress_entry(
                ref_id=case["ref_id"],
                step_code="AI_OVERRIDE",
                step_label="Officer overrode AI category",
                notes=(
                    f"Category changed from "
                            f"'{ai_category}' (AI suggestion) "
                            f"to '{selected_category}'."
                )
            )
            st.session_state.ai_override_logged = True

        st.success("✅ Case category updated successfully")

    st.divider()


    # ─────────────────────────────────────
    # ✅ Officer Action Taken (Form)
    # ─────────────────────────────────────
    st.subheader("Officer Action Taken")

    with st.form("officer_action_form"):
        col1, col2 = st.columns(2)

        with col1:
            action_type = st.selectbox(
                "Action Type",
                [
                    "Site Inspection",
		    "Relevant Agency Consulted",
                    "Phone Call to Resident",
                    "Letter Issued to Resident",
                    "Contractor Engaged",
                    "Follow-up Visit",
                    "Internal Review",
		    "Resident Feedback",
                    "Case Closed",
                    "Other"
                ]
            )

        with col2:
            STATUS_OPTIONS = ["New", "In Progress", "Resolved", "Closed"]

            current_status = case.get("status")

            if current_status in STATUS_OPTIONS:
                status_index = STATUS_OPTIONS.index(current_status)
            else:
                status_index = 0  # default to "New"

            new_status = st.selectbox(
                "Update status",
                STATUS_OPTIONS,
                index=status_index,
                key="case_status_select"
            )

        action_notes = st.text_area(
            "Action Notes",
            height=140,
            placeholder="Describe what was done, findings, outcomes, or next steps...",
            key="officer_action_notes"
        )

        submit_action = st.form_submit_button("Save Action")

    if submit_action:
        save_case_action(
            case_id=case["ref_id"],
            action_type=action_type,
            action_notes=action_notes,
            new_status=new_status
        )
        st.success("✅ Officer action recorded")
        st.rerun()

    st.divider()

    # ─────────────────────────────────────
    # 📜 Actions Taken (Officer)
    # ─────────────────────────────────────
    
    st.subheader("Actions Taken")

    timeline = build_officer_action_timeline(case["ref_id"])

    if not timeline:
        st.info("No officer actions recorded yet.")
    else:
        render_case_timeline(
            timeline=timeline,
            current_status=case.get("status")
        )


    # ------------------------------------------------------------
    # Case Progress (Original Timeline)
    # ------------------------------------------------------------
    st.divider()
    render_case_progress(case["ref_id"])


# ── Mermaid helpers ───────────────────────────────
def clean_mermaid(diagram: str) -> str:
    """
    Cleans AI-generated Mermaid diagrams to prevent syntax errors.
    Removes punctuation that Mermaid cannot parse in node labels.
    """
    diagram = re.sub(
        r"\[(.*?)\]",
        lambda m: f"[{re.sub(r'[,:.]', '', m.group(1))}]",
        diagram
    )
    return diagram

def render_mermaid(code: str):
    components.html(
        f"""
        <div class="mermaid">
        {code}
        </div>

        <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
        <script>
            mermaid.initialize({{ startOnLoad: true, theme: "default" }});
        </script>
        """,
        height=800,
    )
 
 
# ------------------------------------------------------------
# Filters
# ------------------------------------------------------------
colf1, colf2, colf3, colf4 = st.columns(4)
category = colf1.selectbox("Category", ["(All)", "maintenance", "cleanliness", "pests", "parking", "noise", "infrastructure"], index=0)
status = colf2.selectbox("Status", ["(All)", "New", "In Progress", "Resolved", "Closed"], index=0)
query = colf3.text_input("Search (ref, desc, location)")
refresh = colf4.button("Refresh")

filters = {
    "category": None if category == "(All)" else category,
    "status": None if status == "(All)" else status,
    "q": query.strip() or None,
}

rows = list_submissions(filters)

st.caption(f"Showing {len(rows)} cases")
st.dataframe(rows, use_container_width=True)


# ------------------------------------------------------------
# Case details
# ------------------------------------------------------------
st.divider()
ref_id = st.text_input("Open case by Reference ID")
if ref_id:
    match = [r for r in rows if r["ref_id"] == ref_id]
    if not match:
        st.warning("Reference not in current list. Clear filters or refresh.")
    else:
        case = match[0]
        st.subheader(f"Case: {ref_id}")
        col1, col2, col3 = st.columns(3)
        col1.write(f"**Category:** {case['category'] or '-'} (conf: {case['confidence']})")
        col2.write(f"**Urgency:** {case['urgency']}")
        col3.write(f"**Status:** {case['status']}")

        st.write(f"**Description:**\n\n{case['description']}")
        st.write(f"**Location:** {case['location_block'] or ''} {case['location_street'] or ''} | {case['location_text'] or '-'}")
        st.write(f"**Resident:** {case['name'] or '-'} | {case['contact'] or '-'} | Consent: {'Yes' if case['consent'] else 'No'}")
        st.caption(f"Created at: {case['created_at']} | Source: {case['source']}")

        # ------------------------------------------------------------
        # Attachments
        # ------------------------------------------------------------

        atts = get_attachments(ref_id)
        if atts:
            st.write("**Attachments:**")
            for a in atts:
                st.write(f"- {a['filename']}  \n{a['stored_path']}")
        else:
            st.caption("No attachments.")
	# --------------------------------------------------
        # Officer workflow guidance (AI / rules)
        # --------------------------------------------------
        
        st.divider()
        st.subheader("Officer Workflow Guidance")

        workflow = None

        if st.button("Generate workflow guidance"):
            workflow = generate_officer_workflow(ref_id)

            if workflow.get("error"):
                st.error(workflow["error"])
            else:
                st.markdown(f"**Priority level:** {workflow['priority_level']}")
                st.markdown(f"**Recommended status:** {workflow['recommended_status']}")

                st.markdown("### Suggested actions")
                for step in workflow.get("actions", []):
                    st.markdown(f"- {step}")

                if workflow.get("escalate"):
                    st.warning("⚠️ Escalation recommended")

                if workflow.get("notes"):
                    st.caption(workflow["notes"])
		
                
                # Mermaid diagram
                mermaid_diagram = """
                flowchart TD
                    A[Case Received] --> B[Review Case Details]
                    B --> C[Assess Safety Risks]
                    C --> D{Urgent Action Required?}
                    D -- Yes --> E[Escalate]
                    D -- No --> F[Assign Contractor]
                    F --> G[Site Visit]
                    G --> H[Update Resident]
                    H --> I[Update Case Status]
                    E --> H
                """

                
                if workflow.get("mermaid_diagram"):
                    
                    safe_diagram = clean_mermaid(workflow["mermaid_diagram"])
                    render_mermaid(safe_diagram)




                # -----------------------------
                # Visual workflow overview
                # -----------------------------


                st.info(
                    "This guidance is advisory only. "
                    "Final decisions remain with the officer in charge."
                )
         
        # ------------------------------------------------------------
        # Officer decision logging (Governance)
        # ------------------------------------------------------------
        if workflow:
            st.divider()
            st.subheader("Officer Decision")

            decision = st.radio(
                "How do you want to proceed?",
                ["Accept guidance", "Modify guidance", "Reject guidance"],
            )

            notes = st.text_area(
                "Officer notes (optional)",
                placeholder="E.g. Contractor already dispatched earlier.",
            )
   
            if st.button("Record workflow decision"):
                log_workflow_decision(
                    ref_id=ref_id,
                    workflow=workflow,
                    officer_decision=decision,
                    officer_notes=notes.strip() or None,
                )
                st.success("Officer decision recorded.")


        # ------------------------------------------------------------
        # 🛠️ Record Action Taken (Officer)
        # ------------------------------------------------------------

        st.divider()
        st.subheader("🛠️ Record Action Taken")

        action_type = st.selectbox(
            "Action Type",
            [
                "Site inspection conducted",
                "Contractor engaged",
                "Temporary rectification",
                "Repair works completed",
                "Monitoring",
                "Awaiting contractor",
                "Awaiting resident response",
                "No issue found",
                "Escalated to management",
                "Case closed"
            ]
        )

        action_notes = st.text_area(
            "Action Details",
            placeholder="Describe what was done, findings, and outcome...",
            height=120
        )

        if st.button("Save Action Taken"):
            if not action_notes.strip():
                st.warning("Please enter action details before saving.")
            else:
                create_progress_entry(
                    ref_id=ref_id,
                    step_code="ACTION_TAKEN",
                    step_label=action_type,
                    notes=action_notes.strip()
                )
                st.success("Action recorded successfully.")
                st.rerun()

        # ------------------------------------------------------------
        # Status update
        # ------------------------------------------------------------
        st.divider()

        old_status = case["status"] or "New"
        new_status = st.session_state.get("case_status_select", old_status)

        if new_status != old_status:
            update_status(ref_id, new_status)

            create_progress_entry(
                ref_id=ref_id,
                step_code="STATUS_UPDATED",
                step_label=f"Status updated to {new_status}",
                notes=f"Previous status: {old_status}"
            )

            st.success("Status updated and progress recorded.")
        else:
            st.info("Status unchanged. No update recorded.")


# ------------------------------------------------------------
# Export
# ------------------------------------------------------------
st.divider()
if st.button("Export current list to CSV"):
    import pandas as pd
    if rows:
        df = pd.DataFrame(rows)
        st.download_button("Download CSV", data=df.to_csv(index=False).encode("utf-8"), file_name=f"cases_{datetime.now().strftime('%Y%m%d_%H%M')}.csv", mime="text/csv")
    else:
        st.info("Nothing to export for the current filters.")

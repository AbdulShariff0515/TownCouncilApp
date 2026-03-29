# admin_app.py
import os
import re
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, List
import streamlit as st
from dotenv import load_dotenv


from db import (
    init_db,
    list_submissions,
    get_attachments,
    update_status,
    log_workflow_decision,
)

from workflow import generate_officer_workflow
import streamlit.components.v1 as components


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
# Setup
# ------------------------------------------------------------
load_dotenv()
st.set_page_config(page_title="Town Council – Staff Dashboard", page_icon="🗂️", layout="wide")
init_db()

st.title("🗂️ Staff Dashboard — Residents’ Feedback")



# ------------------------------------------------------------
# Simple password protection
# ------------------------------------------------------------
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    pwd = st.text_input("Enter admin password", type="password")
    if pwd and pwd == os.getenv("ADMIN_PASSWORD", "admin"):
        st.session_state.auth = True
        st.rerun()
    st.stop()


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
        # Status update
        # ------------------------------------------------------------
        st.divider()
        new_status = st.selectbox("Update status", ["New", "In Progress", "Resolved", "Closed"], index=["New", "In Progress", "Resolved", "Closed"].index(case["status"] or "New"))
        if st.button("Save status"):
            update_status(ref_id, new_status)
            st.success("Status updated. Click Refresh to reload list.")


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

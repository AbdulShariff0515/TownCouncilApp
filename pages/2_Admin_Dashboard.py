# admin_app.py
import os
import re
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, List
import streamlit as st
from dotenv import load_dotenv

from db import init_db, list_submissions, get_attachments, update_status

load_dotenv()
st.set_page_config(page_title="Town Council – Staff Dashboard", page_icon="🗂️", layout="wide")
init_db()

st.title("🗂️ Staff Dashboard — Residents’ Feedback")

# --- Simple auth ---
pwd = st.text_input("Enter admin password", type="password")
if pwd != os.getenv("ADMIN_PASSWORD", "admin"):
    st.stop()

# --- Filters ---
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

# --- Case details & update ---
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

        # Attachments
        atts = get_attachments(ref_id)
        if atts:
            st.write("**Attachments:**")
            for a in atts:
                st.write(f"- {a['filename']}  \n{a['stored_path']}")
        else:
            st.caption("No attachments.")

        # Update status
        new_status = st.selectbox("Update status", ["New", "In Progress", "Resolved", "Closed"], index=["New", "In Progress", "Resolved", "Closed"].index(case["status"] or "New"))
        if st.button("Save status"):
            update_status(ref_id, new_status)
            st.success("Status updated. Click Refresh to reload list.")

# Export
st.divider()
if st.button("Export current list to CSV"):
    import pandas as pd
    if rows:
        df = pd.DataFrame(rows)
        st.download_button("Download CSV", data=df.to_csv(index=False).encode("utf-8"), file_name=f"cases_{datetime.now().strftime('%Y%m%d_%H%M')}.csv", mime="text/csv")
    else:
        st.info("Nothing to export for the current filters.")

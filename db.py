# db.py


import uuid
from datetime import datetime

# ------------------------------------------------------------
# SQLite database layer for Town Council Feedback System
# ------------------------------------------------------------
# Responsibilities:
# - Initialise database & tables
# - Insert & retrieve resident submissions
# - Store attachments
# - Update case status
# - Support officer workflow governance logging
# ------------------------------------------------------------

import os
import sqlite3
from typing import List, Dict, Optional

DB_PATH = os.path.join("data", "app.db")


# ------------------------------------------------------------
# Connection helper
# ------------------------------------------------------------
def _get_conn():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ------------------------------------------------------------
# Database initialisation
# ------------------------------------------------------------
def init_db():
    conn = _get_conn()
    cur = conn.cursor()

    # --------------------------------------------------------
    # Resident submissions
    # --------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            ref_id TEXT PRIMARY KEY,
            name TEXT,
            contact TEXT,
            consent INTEGER,
            location_block TEXT,
            location_street TEXT,
            location_text TEXT,
            urgency TEXT,
            description TEXT NOT NULL,
            category TEXT,
            confidence REAL,
            source TEXT,
            status TEXT,
            created_at TEXT
        )
    """)

    # --------------------------------------------------------
    # Attachments
    # --------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            mime_type TEXT,
            created_at TEXT,
            FOREIGN KEY (ref_id) REFERENCES submissions(ref_id)
        )
    """)

    # --------------------------------------------------------
    # Officer workflow decisions (Governance & Audit)
    # --------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS workflow_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_id TEXT NOT NULL,
            ai_used INTEGER,
            priority_level TEXT,
            recommended_status TEXT,
            actions_json TEXT,
            officer_decision TEXT,
            officer_notes TEXT,
            created_at TEXT,
            FOREIGN KEY (ref_id) REFERENCES submissions(ref_id)
        )
    """)


    # --------------------------------------------------------
    # Case progress timeline (Phase 1 foundation for Phase 2)
    # --------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS progress_entries (
            id TEXT PRIMARY KEY,
            ref_id TEXT NOT NULL,
            step_code TEXT NOT NULL,
            step_label TEXT NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (ref_id) REFERENCES submissions(ref_id)
        )
    """)


    # Index to speed up timeline lookups by case
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_progress_entries_ref
        ON progress_entries (ref_id)
    """)

    conn.commit()
    conn.close()


# ------------------------------------------------------------
# Insert submission
# ------------------------------------------------------------
def insert_submission(record: Dict):
    conn = _get_conn()
    cur = conn.cursor()

    columns = ", ".join(record.keys())
    placeholders = ", ".join("?" for _ in record)

    cur.execute(
        f"INSERT INTO submissions ({columns}) VALUES ({placeholders})",
        tuple(record.values())
    )

    conn.commit()
    conn.close()


# ------------------------------------------------------------
# Insert attachment
# ------------------------------------------------------------
def insert_attachment(
    ref_id: str,
    filename: str,
    stored_path: str,
    mime_type: Optional[str],
    created_at: str,
):
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO attachments
        (ref_id, filename, stored_path, mime_type, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (ref_id, filename, stored_path, mime_type, created_at))

    conn.commit()
    conn.close()


# ------------------------------------------------------------
# List submissions (with filters)
# ------------------------------------------------------------
def list_submissions(filters: Dict) -> List[Dict]:
    conn = _get_conn()
    cur = conn.cursor()

    sql = "SELECT * FROM submissions WHERE 1=1"
    params = []

    if filters.get("category"):
        sql += " AND category = ?"
        params.append(filters["category"])

    if filters.get("status"):
        sql += " AND status = ?"
        params.append(filters["status"])

    if filters.get("q"):
        q = f"%{filters['q']}%"
        sql += """
            AND (
                ref_id LIKE ?
                OR description LIKE ?
                OR location_text LIKE ?
                OR location_block LIKE ?
                OR location_street LIKE ?
            )
        """
        params.extend([q, q, q, q, q])

    sql += " ORDER BY created_at DESC"

    rows = cur.execute(sql, params).fetchall()
    conn.close()

    return [dict(r) for r in rows]


# ------------------------------------------------------------
# Get single submission by reference ID
# ------------------------------------------------------------
def get_submission_by_ref(ref_id: str) -> Optional[Dict]:
    conn = _get_conn()
    cur = conn.cursor()

    row = cur.execute(
        "SELECT * FROM submissions WHERE ref_id = ?",
        (ref_id,),
    ).fetchone()

    conn.close()
    return dict(row) if row else None


# ------------------------------------------------------------
# Get attachments for a case
# ------------------------------------------------------------
def get_attachments(ref_id: str) -> List[Dict]:
    conn = _get_conn()
    cur = conn.cursor()

    rows = cur.execute(
        "SELECT * FROM attachments WHERE ref_id = ? ORDER BY created_at",
        (ref_id,),
    ).fetchall()

    conn.close()
    return [dict(r) for r in rows]


# ------------------------------------------------------------
# Update case status
# ------------------------------------------------------------
def update_status(ref_id: str, new_status: str):
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE submissions
        SET status = ?
        WHERE ref_id = ?
    """, (new_status, ref_id))

    conn.commit()
    conn.close()

# ------------------------------------------------------------
# Update case category
# ------------------------------------------------------------
def update_case_category(
    case_id: str,
    category: str,
    updated_by: str,
):
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE submissions
        SET
            category = ?
        WHERE ref_id = ?
    """, (
        category,
        case_id,
    ))

    conn.commit()
    conn.close()

# ------------------------------------------------------------
# Log officer workflow decision (AI governance)
# ------------------------------------------------------------
def log_workflow_decision(
    ref_id: str,
    workflow: Dict,
    officer_decision: str,
    officer_notes: Optional[str],
):
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO workflow_decisions (
            ref_id,
            ai_used,
            priority_level,
            recommended_status,
            actions_json,
            officer_decision,
            officer_notes,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, (
        ref_id,
        1 if workflow.get("notes", "").lower().startswith("ai") else 0,
        workflow.get("priority_level"),
        workflow.get("recommended_status"),
        str(workflow.get("actions")),
        officer_decision,
        officer_notes,
    ))

    conn.commit()
    conn.close()

# ------------------------------------------------------------
# Create case progress entry (operational timeline)
# ------------------------------------------------------------
def create_progress_entry(
    ref_id: str,
    step_code: str,
    step_label: str,
    notes: Optional[str] = None,
):
    
    # ✅ Defensive guard – catches bad callers early
    if not step_code or not step_label:
        raise ValueError("step_code and step_label are required")

    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO progress_entries (
            id,
            ref_id,
            step_code,
            step_label,
            notes,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        str(uuid.uuid4()),
        ref_id,
        step_code,
        step_label,
        notes,
        datetime.utcnow().isoformat(timespec="seconds"),
    ))

    conn.commit()
    conn.close()

# ------------------------------------------------------------
# List case progress entries (timeline)
# ------------------------------------------------------------
def list_progress_entries(ref_id: str) -> List[Dict]:
    conn = _get_conn()
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT
            step_code,
            step_label,
            notes,
            created_at
        FROM progress_entries
        WHERE ref_id = ?
        ORDER BY created_at ASC
    """, (ref_id,)).fetchall()

    conn.close()
    return [dict(r) for r in rows]


# ------------------------------------------------------------
# Phase 1 adapter: Case lookup by reference ID
# ------------------------------------------------------------
def get_case_by_reference_id(ref_id: str) -> Optional[Dict]:
    return get_submission_by_ref(ref_id)

# ------------------------------------------------------------
# Phase 1 adapter: Officer notes (internal)
# ------------------------------------------------------------
def get_officer_notes(ref_id: str) -> str:
    conn = _get_conn()
    cur = conn.cursor()

    row = cur.execute("""
        SELECT officer_notes
        FROM workflow_decisions
        WHERE ref_id = ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (ref_id,)).fetchone()

    conn.close()
    return row["officer_notes"] if row and row["officer_notes"] else ""


def save_officer_notes(ref_id: str, notes: str):
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO workflow_decisions (
            ref_id,
            ai_used,
            officer_notes,
            created_at
        )
        VALUES (?, 0, ?, datetime('now'))
    """, (ref_id, notes))

    conn.commit()
    conn.close()

# ------------------------------------------------------------
# Phase 1 adapter: Save officer action
# ------------------------------------------------------------
def save_case_action(
    case_id: str,
    action_type: str,
    action_notes: str,
    new_status: str,
):
    create_progress_entry(
        ref_id=case_id,
        step_code=action_type.lower().replace(" ", "_"),
        step_label=action_type,
        notes=action_notes,
    )

    update_status(case_id, new_status)


# ------------------------------------------------------------
# Phase 1 adapter: Get case action timeline (normalized for UI)
# ------------------------------------------------------------
def get_case_actions(ref_id: str) -> List[Dict]:
    raw_entries = list_progress_entries(ref_id)

    actions = []
    for entry in raw_entries:
        actions.append({
            "action_type": entry["step_label"],
            "action_notes": entry["notes"],
            "new_status": None,  # status already updated in submissions
            "created_at": entry["created_at"],
        })

    return actions

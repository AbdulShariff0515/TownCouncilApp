# db.py
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

# db.py
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = str(DATA_DIR / "app.db")

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ref_id TEXT UNIQUE NOT NULL,
  name TEXT,
  contact TEXT,
  consent INTEGER DEFAULT 0,
  location_text TEXT,
  location_block TEXT,
  location_street TEXT,
  urgency TEXT,
  description TEXT NOT NULL,
  category TEXT,
  confidence REAL DEFAULT 0.0,
  source TEXT,
  status TEXT DEFAULT 'New',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ref_id TEXT NOT NULL,
  filename TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  mime_type TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (ref_id) REFERENCES submissions(ref_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_submissions_ref ON submissions(ref_id);
CREATE INDEX IF NOT EXISTS idx_submissions_cat ON submissions(category);
CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status);
CREATE INDEX IF NOT EXISTS idx_attachments_ref ON attachments(ref_id);
"""

@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    try:
        yield c
        c.commit()
    finally:
        c.close()

def init_db():
    with conn() as c:
        c.executescript(SCHEMA)

def insert_submission(record: Dict[str, Any]):
    keys = ",".join(record.keys())
    qs = ",".join(["?"] * len(record))
    with conn() as c:
        c.execute(f"INSERT INTO submissions ({keys}) VALUES ({qs})", list(record.values()))

def insert_attachment(ref_id: str, filename: str, stored_path: str, mime_type: Optional[str], created_at: str):
    with conn() as c:
        c.execute(
            "INSERT INTO attachments (ref_id, filename, stored_path, mime_type, created_at) VALUES (?,?,?,?,?)",
            (ref_id, filename, stored_path, mime_type, created_at),
        )

def list_submissions(filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    sql = """SELECT ref_id,name,contact,consent,location_text,location_block,location_street,
                    urgency,description,category,confidence,source,status,created_at
             FROM submissions WHERE 1=1"""
    params = []
    if cat := filters.get("category"):
        sql += " AND category = ?"
        params.append(cat)
    if status := filters.get("status"):
        sql += " AND status = ?"
        params.append(status)
    if q := filters.get("q"):
        sql += " AND (ref_id LIKE ? OR description LIKE ? OR location_text LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    sql += " ORDER BY created_at DESC LIMIT 1000"
    with conn() as c:
        cur = c.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

def get_attachments(ref_id: str) -> List[Dict[str, Any]]:
    with conn() as c:
        cur = c.execute(
            "SELECT id, filename, stored_path, mime_type, created_at FROM attachments WHERE ref_id=? ORDER BY created_at",
            (ref_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

def update_status(ref_id: str, new_status: str):
    with conn() as c:
        c.execute("UPDATE submissions SET status=? WHERE ref_id=?", (new_status, ref_id))
"""SQLite patient database — persists processed patient records."""
import sqlite3
from contextlib import contextmanager
import config


@contextmanager
def _conn():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db() -> None:
    with _conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS patients (
                patient_id TEXT NOT NULL,
                patient_name TEXT,
                first_name TEXT,
                medicare_number TEXT,
                irn TEXT,
                dob TEXT,
                last_workflow TEXT,
                last_actioned TEXT,
                PRIMARY KEY (patient_id)
            )
        """)


def upsert_patient(
    patient_id: str,
    patient_name: str,
    first_name: str,
    medicare_number: str,
    irn: str,
    dob: str,
    workflow: str,
) -> None:
    from datetime import datetime
    with _conn() as con:
        con.execute("""
            INSERT INTO patients (patient_id, patient_name, first_name, medicare_number, irn, dob, last_workflow, last_actioned)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(patient_id) DO UPDATE SET
                patient_name=excluded.patient_name,
                first_name=excluded.first_name,
                medicare_number=excluded.medicare_number,
                irn=excluded.irn,
                dob=excluded.dob,
                last_workflow=excluded.last_workflow,
                last_actioned=excluded.last_actioned
        """, (patient_id, patient_name, first_name, medicare_number, irn, dob, workflow, datetime.now().isoformat()))


def search_patients(query: str = "") -> list[dict]:
    with _conn() as con:
        q = f"%{query}%"
        rows = con.execute("""
            SELECT * FROM patients
            WHERE patient_name LIKE ? OR medicare_number LIKE ?
            ORDER BY last_actioned DESC
        """, (q, q)).fetchall()
    return [dict(r) for r in rows]

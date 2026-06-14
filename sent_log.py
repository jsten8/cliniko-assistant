"""Reads and writes sent_log.json. Handles stale record pruning (90 days)."""
import json
from datetime import datetime, timedelta
from pathlib import Path
import config


def _load() -> dict:
    if not config.SENT_LOG_PATH.exists():
        return {"last_run": None, "sent": []}
    try:
        return json.loads(config.SENT_LOG_PATH.read_text())
    except Exception:
        return {"last_run": None, "sent": []}


def _save(data: dict) -> None:
    config.SENT_LOG_PATH.write_text(json.dumps(data, indent=2))


def get_sent_keys() -> set[str]:
    data = _load()
    cutoff = datetime.now() - timedelta(days=90)
    return {
        f"{r['patient_id']}::{r['file_name']}"
        for r in data.get("sent", [])
        if datetime.fromisoformat(r["sent_at"]) > cutoff
    }


def mark_sent(patient_id: str, file_name: str, appointment_date: str) -> None:
    data = _load()
    # Prune stale records (>90 days) on every write
    cutoff = datetime.now() - timedelta(days=90)
    data["sent"] = [
        r for r in data.get("sent", [])
        if datetime.fromisoformat(r["sent_at"]) > cutoff
    ]
    data["sent"].append({
        "patient_id": str(patient_id),
        "file_name": file_name,
        "sent_at": datetime.now().isoformat(),
        "appointment_date": appointment_date,
    })
    _save(data)


def update_last_run() -> None:
    data = _load()
    data["last_run"] = datetime.now().isoformat()
    _save(data)


def get_last_run() -> datetime | None:
    data = _load()
    lr = data.get("last_run")
    return datetime.fromisoformat(lr) if lr else None


def is_sent(patient_id: str, file_name: str) -> bool:
    key = f"{patient_id}::{file_name}"
    return key in get_sent_keys()

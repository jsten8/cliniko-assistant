"""Scans Cliniko for recently uploaded EPC/DVA/Workcover files and builds the worklist."""
from __future__ import annotations
import time
import cliniko
import sent_log
import config

_PDF_EXTENSIONS = {'.pdf', '.docx', '.doc'}


def _matches_worklist(filename: str) -> bool:
    name = filename.lower()
    ext = '.' + name.rsplit('.', 1)[-1] if '.' in name else ''
    if ext not in _PDF_EXTENSIONS:
        return False
    return any(kw.lower() in name for kw in config.WORKLIST_KEYWORDS)


def _detect_workflow(filename: str) -> str:
    name = filename.lower()
    is_final = any(w in name for w in ["final", "last", "discharge", "completion"])
    if "epc" in name:
        return "epc_final" if is_final else "epc_new"
    if "dva" in name:
        return "dva_final" if is_final else "dva_new"
    if "workcover" in name or " wc" in name or name.startswith("wc"):
        return "wc_final_form032" if is_final else "wc_new"
    return "epc_new"


def build_worklist(days: int, progress_callback=None) -> list[dict]:
    """
    Scan global patient_attachments sorted by upload date descending.
    Stops once attachments are older than cutoff. Looks up patient name per match.
    """
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()

    print(f"[worklist] build_worklist(days={days}, cutoff={cutoff})")
    if progress_callback:
        progress_callback("Scanning recently uploaded files...")

    # Fetch one page of recent attachments — filter by cutoff and keywords immediately
    # Cap at 100 results; we stop as soon as all on a page are older than cutoff
    print("[worklist] Calling Cliniko /patient_attachments ...")
    raw = cliniko._get(
        "/patient_attachments",
        {"sort": "created_at", "order": "desc", "per_page": 100},
    )
    print(f"[worklist] Got response from Cliniko. Keys: {list(raw.keys())[:5]}")
    all_atts = []
    for key, val in raw.items():
        if isinstance(val, list):
            all_atts = val
            break

    print(f"[worklist] Total attachments on page: {len(all_atts)}")
    # Filter to worklist keywords AND within cutoff — no need to paginate further
    matching_atts = [
        a for a in all_atts
        if _matches_worklist(a.get("filename", ""))
        and (a.get("created_at") or "")[:10] >= cutoff
    ]

    print(f"[worklist] Matching attachments after filter: {len(matching_atts)}")
    if not matching_atts:
        return []

    sent_keys = sent_log.get_sent_keys()
    entries = []
    total = len(matching_atts)

    # Dedupe by patient — only fetch each patient record once
    patient_cache: dict[str, dict] = {}

    for i, att in enumerate(matching_atts, 1):
        if progress_callback:
            progress_callback(f"Looking up patient {i} of {total}...")

        pid = att.get("patient", {}).get("links", {}).get("self", "").rstrip("/").split("/")[-1]
        if not pid:
            continue

        if pid not in patient_cache:
            print(f"[worklist] Fetching patient {pid} ...")
            try:
                patient_cache[pid] = cliniko.fetch_patient(pid)
                print(f"[worklist] Got patient {pid}")
            except Exception as ex:
                print(f"[worklist] Patient {pid} fetch failed: {ex}")
                patient_cache[pid] = {}

        patient = patient_cache[pid]
        full_name = f"{patient.get('first_name', '')} {patient.get('last_name', '')}".strip()
        fname = att.get("filename", "")
        uploaded = (att.get("created_at") or "")[:10]
        key = f"{pid}::{fname}"

        entries.append({
            "patient_id": pid,
            "patient_name": full_name,
            "patient_first_name": patient.get("first_name", ""),
            "patient_dob": patient.get("date_of_birth", ""),
            "file_name": fname,
            "file_id": att.get("id", ""),
            "download_url": cliniko.get_attachment_content_url(att),
            "created_at": uploaded,
            "appointment_date": uploaded,
            "workflow": _detect_workflow(fname),
            "sent": key in sent_keys,
        })

    # Unsent first (by upload date desc), sent at bottom
    entries.sort(key=lambda e: (e["sent"], e["appointment_date"]), reverse=False)
    entries.sort(key=lambda e: e["sent"])

    return entries


def get_all_attachments_for_patient(patient_id: str) -> list[dict]:
    """Return all worklist-matching attachments for a patient, with recommended one flagged."""
    attachments = cliniko.fetch_patient_attachments(patient_id)
    matched = [a for a in attachments if _matches_worklist(a.get("filename", ""))]
    matched.sort(key=lambda a: a.get("created_at", ""), reverse=True)

    recommended_id = None
    for a in matched:
        name = a.get("filename", "").lower()
        if any(kw.lower() in name for kw in config.PREFERRED_KEYWORDS):
            recommended_id = a.get("id")
            break
    if recommended_id is None and matched:
        recommended_id = matched[0].get("id")

    for a in matched:
        a["recommended"] = (a.get("id") == recommended_id)
        a["download_url"] = cliniko.get_attachment_content_url(a)

    return matched

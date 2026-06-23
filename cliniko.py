"""Cliniko API client — all network calls live here."""
import httpx
import base64
from datetime import date, timedelta
from typing import Any
import config


def _auth() -> tuple[str, str]:
    return (config.CLINIKO_API_KEY, "")


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": "ClinikAssistant/1.0 (jacob.stenholm@covetrus.com)",
    }


def _get(path: str, params: dict | None = None) -> dict[str, Any]:
    import time
    url = f"{config.BASE_URL}{path}"
    with httpx.Client(timeout=30) as client:
        for attempt in range(3):
            resp = client.get(url, auth=_auth(), headers=_headers(), params=params or {})
            if resp.status_code == 429:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return resp.json()


def _get_all_pages(path: str, params: dict | None = None, stop_before: str | None = None, date_field: str = "starts_at") -> list[dict]:
    """
    Fetch pages from a Cliniko endpoint.
    stop_before: ISO date string — stop paginating once all items on a page are older than this.
    """
    import time as _time
    results = []
    url = f"{config.BASE_URL}{path}"
    params = dict(params or {})
    params.setdefault("per_page", 100)
    with httpx.Client(timeout=30) as client:
        while url:
            for attempt in range(4):
                resp = client.get(url, auth=_auth(), headers=_headers(), params=params)
                if resp.status_code == 429:
                    _time.sleep(2 ** attempt)
                    continue
                break
            resp.raise_for_status()
            data = resp.json()
            items = []
            for key, val in data.items():
                if isinstance(val, list):
                    items = val
                    break
            results.extend(items)
            # If all items on this page are older than cutoff, stop fetching
            if stop_before and items:
                oldest = min(i.get(date_field, "9999") for i in items)
                if oldest < stop_before:
                    break
            links = data.get("links", {})
            next_url = links.get("next")
            url = next_url if next_url else None
            params = {}
    return results


def fetch_appointments(days: int) -> list[dict]:
    """Fetch individual appointments from the last N days."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    all_appts = _get_all_pages(
        "/individual_appointments",
        {"sort": "starts_at", "order": "desc"},
        stop_before=cutoff,
        date_field="starts_at",
    )
    return [a for a in all_appts if (a.get("starts_at") or "") >= cutoff]


def fetch_patient(patient_id: str) -> dict:
    return _get(f"/patients/{patient_id}")


def fetch_patient_attachments(patient_id: str) -> list[dict]:
    return _get_all_pages(f"/patients/{patient_id}/patient_attachments")


def get_attachment_content_url(attachment: dict) -> str:
    """Extract the content download URL from an attachment record."""
    return attachment.get("content", {}).get("links", {}).get("self", "")


def download_attachment_bytes(download_url: str) -> bytes:
    import time
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for attempt in range(3):
            resp = client.get(download_url, auth=_auth(), headers=_headers())
            if resp.status_code in (429, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.content
        resp.raise_for_status()
        return resp.content

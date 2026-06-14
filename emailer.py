"""Sends email with PDF attachment via Microsoft Graph API."""
from __future__ import annotations
import base64
from pathlib import Path
import msal
import httpx
import config


def _get_token() -> str:
    app = msal.ConfidentialClientApplication(
        config.MS_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{config.MS_TENANT_ID}",
        client_credential=config.MS_CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"MSAL auth failed: {result.get('error_description', result)}")
    return result["access_token"]


def send_email(
    to: str,
    subject: str,
    body: str,
    pdf_path: Path,
    cc: str | None = None,
) -> None:
    token = _get_token()
    pdf_bytes = pdf_path.read_bytes()
    attachment = {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": pdf_path.name,
        "contentType": "application/pdf",
        "contentBytes": base64.b64encode(pdf_bytes).decode(),
    }
    recipients = [{"emailAddress": {"address": to}}]
    cc_recipients = [{"emailAddress": {"address": cc}}] if cc else []

    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body.replace("\n", "<br>")},
            "toRecipients": recipients,
            "ccRecipients": cc_recipients,
            "attachments": [attachment],
        },
        "saveToSentItems": True,
    }

    url = f"https://graph.microsoft.com/v1.0/users/{config.SENDER_EMAIL}/sendMail"
    with httpx.Client(timeout=60) as client:
        resp = client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        if resp.status_code not in (200, 202):
            raise RuntimeError(f"Graph API error {resp.status_code}: {resp.text}")

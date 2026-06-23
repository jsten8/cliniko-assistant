"""Sends email via Outlook on macOS using AppleScript."""
from __future__ import annotations
import subprocess
from pathlib import Path


def send_email(
    to: str,
    subject: str,
    body: str,
    pdf_path: Path,
    cc: str | None = None,
) -> None:
    """Compose and send an email in Outlook using AppleScript."""
    safe_to = to.replace('"', '')
    safe_subject = subject.replace('"', '').replace('\\', '')
    safe_body = body.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
    safe_path = str(pdf_path).replace('"', '')
    cc_line = f'make new to recipient at end of to recipients with properties {{address:"{safe_to}"}}'
    cc_script = ""
    if cc:
        safe_cc = cc.replace('"', '')
        cc_script = f'make new cc recipient at end of cc recipients with properties {{address:"{safe_cc}"}}'

    script = f"""
tell application "Microsoft Outlook"
    activate
    set newMsg to make new outgoing message with properties {{subject:"{safe_subject}", plain text content:"{safe_body}"}}
    tell newMsg
        {cc_line}
        {cc_script}
        make new attachment with properties {{file:POSIX file "{safe_path}"}}
    end tell
    open newMsg
end tell
"""
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Outlook compose failed: {result.stderr}")

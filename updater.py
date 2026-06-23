"""Auto-updater — downloads latest version from GitHub if a newer one is available."""
from __future__ import annotations
import io
import shutil
import sys
import zipfile
from pathlib import Path

REPO_ZIP = "https://github.com/jsten8/cliniko-assistant/archive/refs/heads/main.zip"
RAW_VERSION = "https://raw.githubusercontent.com/jsten8/cliniko-assistant/main/version.py"
APP_DIR = Path(__file__).parent

# Files/folders to never overwrite during update
PRESERVE = {".env", "patients.db", "sent_log.json", "templates", "email_templates.json"}


def _remote_version() -> str:
    import httpx
    resp = httpx.get(RAW_VERSION, timeout=10, follow_redirects=True)
    for line in resp.text.splitlines():
        if line.startswith("VERSION"):
            return line.split('"')[1]
    return "0.0.0"


def _local_version() -> str:
    try:
        from version import VERSION
        return VERSION
    except Exception:
        return "0.0.0"


def _tuple(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def _log(msg: str) -> None:
    try:
        log_path = APP_DIR / "update.log"
        with open(log_path, "a") as f:
            f.write(msg + "\n")
    except Exception:
        pass
    print(msg)


def check_and_update() -> bool:
    """Returns True if an update was applied (app should restart)."""
    try:
        import httpx
        local = _local_version()
        _log(f"Auto-update check: local={local}")
        remote = _remote_version()
        _log(f"Auto-update check: remote={remote}")
        if _tuple(remote) <= _tuple(local):
            _log("Already up to date.")
            return False

        _log(f"Update available: {local} → {remote}. Downloading...")

        resp = httpx.get(REPO_ZIP, timeout=120, follow_redirects=True)
        z = zipfile.ZipFile(io.BytesIO(resp.content))

        # Extract to a temp dir, then copy files over
        tmp = APP_DIR / "_update_tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        z.extractall(tmp)

        # The zip extracts to a subfolder like cliniko-assistant-main/
        extracted = next(tmp.iterdir())

        for src in extracted.rglob("*"):
            rel = src.relative_to(extracted)
            # Skip preserved files/folders
            if rel.parts[0] in PRESERVE:
                continue
            dst = APP_DIR / rel
            if src.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

        shutil.rmtree(tmp)
        _log(f"Updated to v{remote}. Restarting...")
        return True

    except Exception as e:
        _log(f"Auto-update failed: {e}")
        return False

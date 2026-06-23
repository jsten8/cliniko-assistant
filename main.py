"""Entry point — launches the Cliniko Assistant GUI via pywebview."""
import subprocess
import sys
import threading
from pathlib import Path

APP_DIR = Path(__file__).parent


def _auto_update():
    """Check GitHub for a newer version and apply it if found."""
    try:
        from updater import check_and_update
        updated = check_and_update()
        if updated:
            # Restart the process with the new code
            subprocess.Popen([sys.executable] + sys.argv)
            sys.exit(0)
    except Exception:
        pass


if __name__ == "__main__":
    # Check for updates in background (non-blocking on first run,
    # but restarts if update found before window opens)
    update_thread = threading.Thread(target=_auto_update, daemon=False)
    update_thread.start()
    update_thread.join(timeout=30)  # Wait up to 30s for update check before launching

    import webview
    from api import API

    html_path = APP_DIR / "web" / "index.html"
    window = webview.create_window(
        "Cliniko Assistant — Motion Ease Physiotherapy",
        url=str(html_path),
        js_api=API(),
        width=1200,
        height=800,
        min_size=(900, 600),
        background_color="#F2F0EB",
    )
    webview.start(debug=False)

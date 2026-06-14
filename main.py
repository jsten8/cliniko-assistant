"""Entry point — launches the Cliniko Assistant GUI via pywebview."""
import subprocess
import threading
from pathlib import Path

APP_DIR = Path(__file__).parent


def _git_pull():
    try:
        subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=APP_DIR,
            capture_output=True,
            timeout=15,
        )
    except Exception:
        pass


if __name__ == "__main__":
    threading.Thread(target=_git_pull, daemon=True).start()

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

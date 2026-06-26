"""Entry point — launches the Cliniko Assistant GUI via pywebview."""
import subprocess
import sys
import threading
import json
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
    from api import API, _worklist_future
    from version import VERSION

    # Inject version directly into HTML at runtime so it shows instantly
    html_path = APP_DIR / "web" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    html = html.replace(
        'id="app-version" style="margin-left:8px;opacity:0.5;">',
        f'id="app-version" style="margin-left:8px;opacity:0.5;">v{VERSION}'
    )
    runtime_html = APP_DIR / "web" / "_runtime.html"
    runtime_html.write_text(html, encoding="utf-8")
    html_path = runtime_html

    window = webview.create_window(
        "Cliniko Assistant — Motion Ease Physiotherapy",
        url=str(html_path),
        js_api=API(),
        width=1200,
        height=800,
        min_size=(900, 600),
        background_color="#F2F0EB",
    )

    def _push_worklist():
        """Wait for preloaded worklist then push result to JS via evaluate_js.
        This bypasses the pywebview API bridge entirely."""
        import time, concurrent.futures
        time.sleep(2)  # let the page finish loading
        try:
            entries = _worklist_future.result(timeout=43)
            js = f"window.__pushWorklist({json.dumps(entries)});"
        except concurrent.futures.TimeoutError:
            js = "window.__pushWorklist(null, 'Cliniko took too long to respond (45s). Check your internet connection and click Refresh.');"
        except Exception as e:
            js = f"window.__pushWorklist(null, {json.dumps(str(e))});"
        window.evaluate_js(js)

    threading.Thread(target=_push_worklist, daemon=True).start()
    webview.start(debug=False)

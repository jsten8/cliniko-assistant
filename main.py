"""Entry point — launches the Cliniko Assistant GUI via pywebview."""
import subprocess
import sys
import threading
import json
import socket
import mimetypes
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

APP_DIR = Path(__file__).parent
WEB_DIR = APP_DIR / "web"


def _auto_update():
    """Check GitHub for a newer version and apply it if found."""
    try:
        from updater import check_and_update
        updated = check_and_update()
        if updated:
            subprocess.Popen([sys.executable] + sys.argv)
            sys.exit(0)
    except Exception:
        pass


def _push_worklist_when_ready(window, future):
    """
    Wait for worklist scan to finish then push result into JS via evaluate_js.
    Module-level so it is testable and importable.
    """
    import json as _json
    try:
        entries = future.result(timeout=45)
        window.evaluate_js(f'window.__pushWorklist({_json.dumps(entries)})')
    except Exception as e:
        window.evaluate_js(f'window.__pushWorklist(null, {_json.dumps(str(e))})')


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def _start_app_server(port: int, worklist_future, runtime_html_path: Path, timeout: int = 45):
    """
    HTTP server that serves the app HTML/JS files AND the /worklist JSON endpoint.
    Pointing pywebview at http://127.0.0.1:{port}/ means JS fetch('/worklist')
    is same-origin — no CORS, no file:// restrictions, no evaluate_js needed.
    """
    import concurrent.futures, time

    _worklist_result = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # silence access logs

        def do_GET(self):
            path = self.path.split('?')[0]

            if path == '/worklist':
                body = json.dumps(_worklist_result).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)
                return

            # Serve static files
            if path in ('/', '/index.html'):
                file_path = runtime_html_path
            else:
                file_path = WEB_DIR / path.lstrip('/')

            if file_path.exists() and file_path.is_file():
                data = file_path.read_bytes()
                content_type = mimetypes.guess_type(str(file_path))[0] or 'text/plain'
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404)
                self.end_headers()

    server = HTTPServer(('127.0.0.1', port), Handler)
    server.timeout = 1

    def _serve():
        deadline = time.time() + timeout
        while time.time() < deadline:
            if worklist_future.done():
                break
            server.handle_request()

        try:
            entries = worklist_future.result(timeout=0.1)
            _worklist_result['status'] = 'ok'
            _worklist_result['entries'] = entries
        except concurrent.futures.TimeoutError:
            _worklist_result['status'] = 'timeout'
            _worklist_result['error'] = 'Cliniko scan timed out (45s). Click Refresh.'
        except Exception as e:
            _worklist_result['status'] = 'error'
            _worklist_result['error'] = str(e)

        while True:
            server.handle_request()

    threading.Thread(target=_serve, daemon=True).start()


if __name__ == "__main__":
    update_thread = threading.Thread(target=_auto_update, daemon=False)
    update_thread.start()
    update_thread.join(timeout=30)

    import webview
    from api import API, _worklist_future
    from version import VERSION

    port = _free_port()

    # Inject version into HTML and write runtime file
    html = (APP_DIR / "web" / "index.html").read_text(encoding="utf-8")
    html = html.replace(
        'id="app-version" style="margin-left:8px;opacity:0.5;">',
        f'id="app-version" style="margin-left:8px;opacity:0.5;">v{VERSION}'
    )
    runtime_html = APP_DIR / "web" / "_runtime.html"
    runtime_html.write_text(html, encoding="utf-8")

    # Serve the app AND the worklist endpoint from one HTTP server.
    # pywebview loads http://127.0.0.1:{port}/ so JS fetch('/worklist') is same-origin.
    _start_app_server(port, _worklist_future, runtime_html)

    window = webview.create_window(
        "Cliniko Assistant — Motion Ease Physiotherapy",
        url=f"http://127.0.0.1:{port}/",
        js_api=API(),
        width=1200,
        height=800,
        min_size=(900, 600),
        background_color="#F2F0EB",
    )
    webview.start(debug=False)

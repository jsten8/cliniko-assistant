"""Entry point — launches the Cliniko Assistant GUI via pywebview."""
import subprocess
import sys
import threading
import json
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

APP_DIR = Path(__file__).parent


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


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def _start_data_server(port: int, worklist_future, timeout: int = 45):
    """Tiny HTTP server that serves worklist JSON to the JS frontend."""
    import concurrent.futures, time

    _result = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # silence access logs

        def do_GET(self):
            if self.path.startswith('/worklist'):
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(_result).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

    server = HTTPServer(('127.0.0.1', port), Handler)
    server.timeout = 1  # non-blocking serve_forever

    def _serve():
        deadline = time.time() + timeout
        # Wait for worklist result (or timeout)
        while time.time() < deadline:
            if worklist_future.done():
                break
            server.handle_request()

        try:
            entries = worklist_future.result(timeout=0.1)
            _result['status'] = 'ok'
            _result['entries'] = entries
        except concurrent.futures.TimeoutError:
            _result['status'] = 'timeout'
            _result['error'] = 'Cliniko took too long to respond (45s). Check your internet connection and click Refresh.'
        except Exception as e:
            _result['status'] = 'error'
            _result['error'] = str(e)

        # Keep serving so JS can fetch the result
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

    # Start local data server before opening the window
    port = _free_port()
    _start_data_server(port, _worklist_future, timeout=45)

    # Inject version + data server port into HTML
    html_path = APP_DIR / "web" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    html = html.replace(
        'id="app-version" style="margin-left:8px;opacity:0.5;">',
        f'id="app-version" style="margin-left:8px;opacity:0.5;">v{VERSION}'
    )
    html = html.replace(
        'window.APP_VERSION',
        f'window.__DATA_PORT={port}; window.APP_VERSION'
    )
    runtime_html = APP_DIR / "web" / "_runtime.html"
    runtime_html.write_text(html, encoding="utf-8")

    window = webview.create_window(
        "Cliniko Assistant — Motion Ease Physiotherapy",
        url=str(runtime_html),
        js_api=API(),
        width=1200,
        height=800,
        min_size=(900, 600),
        background_color="#F2F0EB",
    )
    webview.start(debug=False)

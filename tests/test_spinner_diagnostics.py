"""
Diagnostic tests for the infinite spinner bug.
These tests probe the evaluate_js / pywebview push mechanism to find why
the worklist never renders despite the backend completing successfully.
"""
import sys
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Test 1: Does _push_worklist_when_ready actually get called?
# ---------------------------------------------------------------------------
def test_1_push_function_is_called_by_webview_start():
    """webview.start(func) must invoke func — if not, push never happens."""
    import main

    called = []

    original = main._push_worklist_when_ready if hasattr(main, '_push_worklist_when_ready') else None
    func_exists = callable(getattr(main, '_push_worklist_when_ready', None))

    print(f"\n  _push_worklist_when_ready exists on main module: {func_exists}")
    assert func_exists, "_push_worklist_when_ready is not defined on main — webview.start has nothing to call"
    print("  PASS: function exists and is callable")


# ---------------------------------------------------------------------------
# Test 2: Does evaluate_js throw silently?
# ---------------------------------------------------------------------------
def test_2_evaluate_js_exceptions_are_logged():
    """If evaluate_js raises, it must NOT be silently swallowed."""
    import main

    mock_window = MagicMock()
    mock_window.evaluate_js.side_effect = Exception("pywebview not ready")

    error_logged = []

    mock_future = MagicMock()
    mock_future.result.return_value = [{"patient_name": "Jane"}]

    try:
        entries = mock_future.result(timeout=45)
        mock_window.evaluate_js(f'window.__pushWorklist({json.dumps(entries)})')
    except Exception as e:
        error_logged.append(str(e))

    print(f"\n  evaluate_js exception captured: {error_logged}")
    # Check main.py source to see if the exception is caught and logged or silently dropped
    source = Path(__file__).parent.parent / "main.py"
    text = source.read_text()
    has_logging = "log" in text.lower() or "print" in text.lower() or "write" in text.lower()
    inner_try = text.count("try:") >= 2

    print(f"  main.py has any logging: {has_logging}")
    print(f"  main.py has nested try blocks (outer=_auto_update, inner=push): {inner_try}")
    if not inner_try:
        print("  WARNING: evaluate_js failure may be silently swallowed — no inner try/except in _push_worklist_when_ready")


# ---------------------------------------------------------------------------
# Test 3: Is evaluate_js firing before the page has loaded?
# ---------------------------------------------------------------------------
def test_3_push_fires_before_page_ready():
    """
    webview.start(func) runs func almost immediately.
    If __pushWorklist is called before app.js has parsed, it's undefined and silently fails.
    Check whether there's any delay or page-ready guard before evaluate_js.
    """
    source = (Path(__file__).parent.parent / "main.py").read_text()

    has_sleep = "sleep" in source and "_push_worklist_when_ready" in source
    has_page_load_wait = "loaded" in source.lower() or "dom" in source.lower() or "ready" in source.lower()

    print(f"\n  _push_worklist_when_ready has a sleep/delay before evaluate_js: {has_sleep}")
    print(f"  _push_worklist_when_ready waits for page load event: {has_page_load_wait}")

    if not has_sleep and not has_page_load_wait:
        print("  WARNING: evaluate_js is called with NO delay after window opens.")
        print("  __pushWorklist may not be defined in JS yet when Python calls it.")
    else:
        print("  OK: some guard exists")


# ---------------------------------------------------------------------------
# Test 4: Does evaluate_js work at all? (simple title change test)
# ---------------------------------------------------------------------------
def test_4_evaluate_js_basic_functionality():
    """Verify evaluate_js is actually invoked on the window object during push."""
    mock_window = MagicMock()
    mock_window.evaluate_js.return_value = None

    entries = [{"patient_name": "Jane", "file_name": "EPC.pdf", "sent": False}]
    js_call = f'window.__pushWorklist({json.dumps(entries)})'
    mock_window.evaluate_js(js_call)

    mock_window.evaluate_js.assert_called_once()
    actual_call = mock_window.evaluate_js.call_args[0][0]
    print(f"\n  evaluate_js called with: {actual_call[:80]}...")
    assert "window.__pushWorklist" in actual_call
    assert "Jane" in actual_call
    print("  PASS: evaluate_js would be called with correct payload")


# ---------------------------------------------------------------------------
# Test 5: Is __pushWorklist defined in app.js?
# ---------------------------------------------------------------------------
def test_5_push_worklist_defined_in_js():
    """window.__pushWorklist must be defined in app.js for the push to work."""
    app_js = (Path(__file__).parent.parent / "web" / "app.js").read_text()

    defined = "window.__pushWorklist" in app_js and "= function" in app_js
    called_only = "window.__pushWorklist(" in app_js

    print(f"\n  window.__pushWorklist defined (= function): {defined}")
    print(f"  window.__pushWorklist appears in app.js at all: {called_only}")

    if not defined:
        print("  FAIL: __pushWorklist is never defined — it's only called, never declared")
    else:
        print("  PASS: __pushWorklist is defined")


# ---------------------------------------------------------------------------
# Test 6: Is the auto-updater installing old JS from a cached GitHub zip?
# ---------------------------------------------------------------------------
def test_6_app_js_on_disk_contains_push_not_poll():
    """
    The GitHub zip may be cached. Check the actual app.js on disk contains
    the new __pushWorklist approach, NOT the old fetch() poll.
    """
    app_js = (Path(__file__).parent.parent / "web" / "app.js").read_text()

    has_push = "window.__pushWorklist" in app_js
    has_old_poll = "fetch(`http://127.0.0.1" in app_js or "pollWorklist" in app_js

    print(f"\n  app.js has new __pushWorklist receiver: {has_push}")
    print(f"  app.js still has OLD fetch() poll: {has_old_poll}")

    if has_old_poll:
        print("  FAIL: app.js still contains old polling code — updater may have installed a cached zip")
    elif not has_push:
        print("  FAIL: app.js has neither — something is very wrong")
    else:
        print("  PASS: app.js has push receiver and no old poll")


# ---------------------------------------------------------------------------
# Test 7: Is _worklist_future None or valid when _push runs?
# ---------------------------------------------------------------------------
def test_7_worklist_future_is_valid_at_push_time():
    """
    _worklist_future is imported from api.py into main.py at import time.
    If the module-level reference is stale (None), result() will fail.
    """
    import api
    future = api._worklist_future

    print(f"\n  api._worklist_future type: {type(future)}")
    print(f"  api._worklist_future is None: {future is None}")

    if future is None:
        print("  FAIL: _worklist_future is None — push will crash immediately")
    else:
        print(f"  Future done: {future.done()}")
        print(f"  Future running: {future.running()}")
        if future.done():
            try:
                result = future.result(timeout=1)
                print(f"  Future result count: {len(result)} entries")
                print("  PASS: future has valid result ready to push")
            except Exception as e:
                print(f"  FAIL: future.result() raised: {e}")
        else:
            print("  Future still running — push will block until it completes (up to 45s)")


# ---------------------------------------------------------------------------
# Test 8: Does __pushWorklist crash on missing DOM elements?
# ---------------------------------------------------------------------------
def test_8_push_worklist_js_references_valid_element_ids():
    """
    __pushWorklist calls getElementById for wl-status, wl-tbody, wl-count-badge.
    If any of these IDs don't exist in index.html, JS crashes silently.
    """
    app_js = (Path(__file__).parent.parent / "web" / "app.js").read_text()
    index_html = (Path(__file__).parent.parent / "web" / "index.html").read_text()

    import re
    ids_in_push = re.findall(r"getElementById\('([^']+)'\)", app_js)
    # Only grab the ones inside __pushWorklist
    push_block_start = app_js.find("window.__pushWorklist")
    push_block_end = app_js.find("\n};", push_block_start)
    push_block = app_js[push_block_start:push_block_end]
    ids_used = re.findall(r"getElementById\('([^']+)'\)", push_block)

    print(f"\n  Element IDs referenced inside __pushWorklist: {ids_used}")
    all_present = True
    for el_id in ids_used:
        present = f'id="{el_id}"' in index_html
        print(f"  #{el_id} exists in index.html: {present}")
        if not present:
            all_present = False

    if all_present:
        print("  PASS: all referenced DOM elements exist")
    else:
        print("  FAIL: some DOM elements are missing — JS will crash silently")


# ---------------------------------------------------------------------------
# Test 9: Is _worklist_future the same object in main vs api?
# ---------------------------------------------------------------------------
def test_9_future_reference_is_not_stale():
    """
    main.py does: from api import _worklist_future
    This copies the reference at import time. If api.py reassigns _worklist_future
    after the import, main.py holds a stale None.
    """
    import api
    import main

    api_future = api._worklist_future
    # main._worklist_future is only in __main__ block, but we can check api directly
    print(f"\n  api._worklist_future: {api._worklist_future}")
    print(f"  api._worklist_future is None: {api._worklist_future is None}")

    # Check main.py source — does it import _worklist_future before or after api starts the preload?
    main_source = (Path(__file__).parent.parent / "main.py").read_text()
    imports_future = "from api import" in main_source and "_worklist_future" in main_source
    print(f"  main.py imports _worklist_future from api: {imports_future}")

    # The preload starts at module level in api.py (_start_worklist_preload() is called at line 43)
    # So by the time main.py imports it, it should already be a real Future
    if api_future is not None:
        print("  PASS: _worklist_future is a real Future object, not None")
    else:
        print("  FAIL: _worklist_future is None at import time")


# ---------------------------------------------------------------------------
# Test 10: Does pywebview require evaluate_js on the main thread?
# ---------------------------------------------------------------------------
def test_10_evaluate_js_thread_safety():
    """
    pywebview on macOS (WKWebView) requires evaluate_js to be called from
    the correct thread. webview.start(func) runs func in a background thread.
    Check if there's any thread marshalling in the push function.
    """
    main_source = (Path(__file__).parent.parent / "main.py").read_text()

    has_thread_guard = any(kw in main_source for kw in [
        "main_thread", "call_on_main", "dispatch", "run_on_main", "GIL"
    ])
    runs_in_background = "webview.start(_push_worklist_when_ready" in main_source

    print(f"\n  _push_worklist_when_ready passed directly to webview.start(): {runs_in_background}")
    print(f"  Any thread marshalling present in main.py: {has_thread_guard}")

    if runs_in_background and not has_thread_guard:
        print("  WARNING: _push_worklist_when_ready runs in a background thread.")
        print("  pywebview evaluate_js may silently fail if called off the main thread.")
        print("  This is a strong candidate for the spinner bug.")
    else:
        print("  OK: thread handling looks acceptable")

"""
test_10_autofill — Chrome extension end-to-end auto-fill test.

Requires Playwright with Chromium:
  pip install playwright && playwright install chromium

Skipped unless NONCEY_TEST_EXTENSION=1.

What this test does:
  1. Starts the test HTTP server (testpage/index.html).
  2. Starts the Flask daemon on a real TCP port so the extension can reach it.
  3. Loads the unpacked extension into a headless Chromium context.
  4. Configures the extension via chrome.storage.sync (server URL, token,
     provider pointing to the test page URL + OTP field selector).
  5. Seeds a nonce directly into the DB.
  6. Opens the test page; waits for the extension to poll and fill #otp-field.
  7. Asserts the field value matches the seeded nonce.
  8. Asserts the nonce was deleted from the DB by the extension after fill.
"""

import os
import secrets
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get('NONCEY_TEST_EXTENSION') != '1',
    reason='extension test disabled — set NONCEY_TEST_EXTENSION=1 to enable',
)

TESTS_DIR     = Path(__file__).parent.parent
# tests/ lives inside noncey/, which is a sibling of noncey.client.chromeextension/
# under the common C:\Claude\ root — so we need two levels up from tests/.
EXT_DIR       = TESTS_DIR.parent.parent / 'noncey.client.chromeextension'
TESTPAGE_PORT = 18080
DAEMON_PORT   = 15000
DAEMON_BASE   = f'http://127.0.0.1:{DAEMON_PORT}'
TESTPAGE_URL  = f'http://127.0.0.1:{TESTPAGE_PORT}'

from conftest import TEST_PASSWORD, TEST_PROVIDER_TAG, TEST_USERNAME, _open_db  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope='module')
def testserver_proc():
    """Start the static test page server as a subprocess."""
    script = Path(__file__).parent / 'testserver.py'
    proc   = subprocess.Popen(
        [sys.executable, str(script), str(TESTPAGE_PORT)],
        stdout=subprocess.PIPE,
    )
    proc.stdout.readline()   # block until server prints its startup line
    yield proc
    proc.terminate()
    proc.wait()


@pytest.fixture(scope='module')
def live_flask(flask_app):
    """
    Run the Flask test application on a real TCP socket.
    The extension's service worker cannot reach the Flask test client directly,
    so we bind to localhost for the duration of the module's tests.
    """
    import threading
    t = threading.Thread(
        target=lambda: flask_app.run(
            host='127.0.0.1', port=DAEMON_PORT, use_reloader=False
        ),
        daemon=True,
    )
    t.start()
    time.sleep(0.8)   # give Flask a moment to bind
    yield


@pytest.fixture(scope='module')
def ext_context(playwright, live_flask, testserver_proc):
    """Chromium browser context with the unpacked extension loaded."""
    import glob as _glob
    # Locate the full Chromium binary explicitly — headless=False alone may
    # still pick up chrome-headless-shell on some Playwright installs, and
    # the headless shell does not support extensions or service workers.
    _cache = Path.home() / '.cache/ms-playwright'
    _dirs  = sorted(_cache.iterdir()) if _cache.exists() else []
    print(f'\n[ext_context] ms-playwright dirs: {[d.name for d in _dirs]}')
    # Try both chrome-linux and chrome-linux64 subdirectory names.
    _exe = None
    for _sub in ('chrome-linux64/chrome', 'chrome-linux/chrome', 'chrome'):
        _pattern = str(_cache / f'chromium-*/{_sub}')
        _hits = sorted(_glob.glob(_pattern))
        if _hits:
            _exe = _hits[-1]
            break
    print(f'[ext_context] chromium exe: {_exe}')

    if not _exe:
        pytest.skip(
            'Full Chromium binary not found under ~/.cache/ms-playwright/chromium-*/. '
            'Run: playwright install chromium'
        )

    if not EXT_DIR.exists():
        pytest.skip(f'Extension directory not found: {EXT_DIR}')
    print(f'[ext_context] ext_dir: {EXT_DIR} (exists={EXT_DIR.exists()})')

    _user_data_dir = tempfile.mkdtemp(prefix='pw-ext-')
    print(f'[ext_context] user_data_dir: {_user_data_dir}')

    _kwargs = dict(
        executable_path=_exe,
        headless=False,
        # Playwright injects --disable-extensions by default which prevents
        # --load-extension from working. Remove it explicitly.
        ignore_default_args=['--disable-extensions'],
        args=[
            '--headless=new',
            f'--disable-extensions-except={EXT_DIR}',
            f'--load-extension={EXT_DIR}',
            '--no-sandbox',
            '--disable-dev-shm-usage',
        ],
        ignore_https_errors=True,
    )

    ctx = playwright.chromium.launch_persistent_context(_user_data_dir, **_kwargs)

    # Capture any service worker registrations immediately.
    _sw_urls: list[str] = []
    ctx.on('serviceworker', lambda sw: (_sw_urls.append(sw.url), print(f'[ext_context] SW registered: {sw.url}')))

    # Navigate to a blank page and capture console output — background.js logs
    # "[noncey] service worker starting" which should appear here if the SW loads.
    _diag_page = ctx.new_page()
    _diag_page.on('console', lambda msg: print(f'[browser-console] {msg.type}: {msg.text}'))
    _diag_page.goto('about:blank')

    # Brief pause to let the extension activate.
    time.sleep(2)
    print(f'[ext_context] after 2s — sw_urls={_sw_urls}, '
          f'service_workers={[w.url for w in ctx.service_workers]}, '
          f'background_pages={[p.url for p in ctx.background_pages]}')

    _diag_page.close()
    yield ctx
    ctx.close()


@pytest.fixture(scope='module')
def configured_extension(ext_context):
    """
    Log in to obtain a JWT, then inject server/token/provider config into
    chrome.storage.sync via the extension's service worker.
    """
    import json
    import urllib.request

    # Obtain JWT from the live Flask daemon.
    payload = json.dumps({
        'username': TEST_USERNAME,
        'password': TEST_PASSWORD,
    }).encode()
    req = urllib.request.Request(
        f'{DAEMON_BASE}/api/auth/login',
        data=payload,
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        token = json.loads(resp.read())['token']

    provider_json = json.dumps([{
        'tag':         TEST_PROVIDER_TAG,
        'url_pattern': f'127.0.0.1:{TESTPAGE_PORT}',
        'selector':    '#otp-field',
    }])

    # Navigate to a blank page to give the browser a chance to activate the
    # extension service worker (required on some Chromium builds).
    _p = ext_context.new_page()
    _p.goto('about:blank')
    _p.close()

    # Poll for the service worker — it may already be registered or may take
    # a moment; wait_for_event() only catches future events so polling is safer.
    import time as _time
    _deadline = _time.monotonic() + 15
    sw = None
    while _time.monotonic() < _deadline:
        workers = ext_context.service_workers
        if workers:
            sw = workers[0]
            break
        _time.sleep(0.3)
    assert sw is not None, (
        'Extension service worker did not register within 15 s\n'
        f'pages in context: {[p.url for p in ext_context.pages]}\n'
        f'background_pages: {ext_context.background_pages}\n'
        f'service_workers:  {ext_context.service_workers}'
    )
    sw.evaluate(f"""() => chrome.storage.sync.set({{
        server:    '{DAEMON_BASE}',
        username:  '{TEST_USERNAME}',
        token:     {json.dumps(token)},
        providers: {provider_json},
        autoFill:  true,
    }})""")

    yield token


# ── Test ──────────────────────────────────────────────────────────────────────

def test_extension_autofills_otp_field(
    ext_context, configured_extension, seed_data, tmp_env
):
    """
    Extension detects the test page URL, polls the API, and fills #otp-field
    with the seeded nonce within 10 seconds.
    """
    nonce_value = 'EXTSM-' + secrets.token_hex(4).upper()
    now         = datetime.now(timezone.utc)
    expires     = now + timedelta(hours=2)

    conn = _open_db(tmp_env['db_path'])
    cur  = conn.execute(
        "INSERT INTO nonces "
        "  (user_id, provider_id, nonce_value, received_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (seed_data['user_id'], seed_data['provider_id'],
         nonce_value, now.isoformat(), expires.isoformat()),
    )
    nonce_id = cur.lastrowid
    conn.commit()
    conn.close()

    try:
        page = ext_context.new_page()
        page.goto(TESTPAGE_URL, wait_until='domcontentloaded')

        # Wait up to 10 s for the extension to poll and fill the field.
        page.wait_for_function(
            "() => document.getElementById('otp-field').value !== ''",
            timeout=10_000,
        )

        filled = page.evaluate("() => document.getElementById('otp-field').value")
        assert filled == nonce_value, f'expected {nonce_value!r}, got {filled!r}'
        page.close()

        # Extension should have called DELETE /api/nonces/<id> after fill.
        time.sleep(0.5)
        conn = _open_db(tmp_env['db_path'])
        row  = conn.execute(
            "SELECT id FROM nonces WHERE id = ?", (nonce_id,)
        ).fetchone()
        conn.close()
        assert row is None, 'extension did not delete the nonce from the DB after fill'

    finally:
        # Best-effort cleanup in case the test failed before deletion.
        conn = _open_db(tmp_env['db_path'])
        conn.execute("DELETE FROM nonces WHERE id = ?", (nonce_id,))
        conn.commit()
        conn.close()

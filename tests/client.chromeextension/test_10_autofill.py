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
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get('NONCEY_TEST_EXTENSION') != '1',
    reason='extension test disabled — set NONCEY_TEST_EXTENSION=1 to enable',
)

TESTS_DIR     = Path(__file__).parent.parent
EXT_DIR       = TESTS_DIR.parent / 'noncey.client.chromeextension'
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
    ctx = playwright.chromium.launch_persistent_context(
        '',
        headless=True,
        args=[
            f'--disable-extensions-except={EXT_DIR}',
            f'--load-extension={EXT_DIR}',
            '--no-sandbox',
        ],
        ignore_https_errors=True,
    )
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

    sw = ext_context.service_workers[0]
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

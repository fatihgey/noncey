"""
test_05_mail — End-to-end mail delivery test.

Requires a running Postfix with the noncey nonce-pipe transport installed.
Skipped unless NONCEY_TEST_MAIL=1.

The test sends a real SMTP message to the local MTA, then polls the SQLite DB
until the nonce appears (or times out).  The nonce is deleted from the DB on
teardown regardless of whether the test passed.

Environment variables:
  NONCEY_TEST_MAIL=1          enable this test (required)
  NONCEY_TEST_SMTP_HOST       SMTP host (default: localhost)
  NONCEY_TEST_SMTP_PORT       SMTP port (default: 25)

On failure, check: journalctl -u postfix -n 50
"""

import os
import secrets
import smtplib
import time
from email.mime.text import MIMEText

import pytest

from conftest import (
    TEST_DOMAIN,
    TEST_SENDER,
    TEST_START_MARKER,
    TEST_END_MARKER,
    TEST_USERNAME,
    _open_db,
)

pytestmark = pytest.mark.skipif(
    os.environ.get('NONCEY_TEST_MAIL') != '1',
    reason='live mail test disabled — set NONCEY_TEST_MAIL=1 to enable',
)

SMTP_HOST     = os.environ.get('NONCEY_TEST_SMTP_HOST', 'localhost')
SMTP_PORT     = int(os.environ.get('NONCEY_TEST_SMTP_PORT', '25'))
POLL_TIMEOUT  = 15    # seconds to wait for Postfix delivery
POLL_INTERVAL = 0.5


def _send(nonce_value: str) -> None:
    body = (
        f"This is an automated noncey smoke-test message.\n\n"
        f"Your one-time code: "
        f"{TEST_START_MARKER}{nonce_value}{TEST_END_MARKER}\n"
    )
    msg            = MIMEText(body)
    msg['From']    = TEST_SENDER
    msg['To']      = f'nonce-{TEST_USERNAME}@{TEST_DOMAIN}'
    msg['Subject'] = 'noncey smoke test'

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
        smtp.sendmail(TEST_SENDER, [msg['To']], msg.as_string())


def test_mail_delivery_end_to_end(tmp_env, seed_data):
    """
    Send email via SMTP → Postfix → nonce-pipe → ingest.py → SQLite.
    Verifies the nonce appears in the DB within POLL_TIMEOUT seconds.
    """
    nonce_value = 'MAILSMOKE-' + secrets.token_hex(4).upper()
    _send(nonce_value)

    nonce_id = None
    deadline = time.monotonic() + POLL_TIMEOUT
    while time.monotonic() < deadline:
        conn = _open_db(tmp_env['db_path'])
        row  = conn.execute(
            "SELECT id FROM nonces WHERE user_id = ? AND nonce_value = ?",
            (seed_data['user_id'], nonce_value),
        ).fetchone()
        conn.close()
        if row:
            nonce_id = row[0]
            break
        time.sleep(POLL_INTERVAL)

    # Cleanup regardless of outcome.
    if nonce_id is not None:
        conn = _open_db(tmp_env['db_path'])
        conn.execute("DELETE FROM nonces WHERE id = ?", (nonce_id,))
        conn.commit()
        conn.close()

    assert nonce_id is not None, (
        f"Nonce {nonce_value!r} not found in DB after {POLL_TIMEOUT}s.\n"
        "Diagnostics: journalctl -u postfix -n 50"
    )

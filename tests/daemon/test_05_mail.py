"""
test_05_mail — End-to-end mail delivery test.

Requires a running Postfix with the noncey nonce-pipe transport installed.
Skipped unless NONCEY_TEST_MAIL=1.

The test sends a real SMTP message to the local MTA via the production Postfix
transport, then polls the production SQLite DB until the nonce appears (or
times out).  The _test_ user is seeded into the production DB for the duration
of the test and removed on teardown.

The MX domain and DB path are read directly from NONCEY_TEST_MAIL_CONF so no
extra env vars are needed beyond the two below.

Environment variables:
  NONCEY_TEST_MAIL=1              enable this test (required)
  NONCEY_TEST_MAIL_CONF           path to the noncey.conf used by the Postfix
                                  pipe transport  (default: /etc/noncey/noncey.conf)
  NONCEY_TEST_SMTP_HOST           SMTP host  (default: localhost)
  NONCEY_TEST_SMTP_PORT           SMTP port  (default: 25)

On failure, check: journalctl -u postfix -n 50
"""

import configparser
import os
import secrets
import smtplib
import time
from email.mime.text import MIMEText

import bcrypt
import pytest

from conftest import (
    TEST_PASSWORD,
    TEST_PROVIDER_TAG,
    TEST_SENDER,
    TEST_START_MARKER,
    TEST_END_MARKER,
    TEST_SUBJECT_PATTERN,
    TEST_USERNAME,
    _open_db,
)

pytestmark = pytest.mark.skipif(
    os.environ.get('NONCEY_TEST_MAIL') != '1',
    reason='live mail test disabled — set NONCEY_TEST_MAIL=1 to enable',
)

SMTP_HOST     = os.environ.get('NONCEY_TEST_SMTP_HOST', 'localhost')
SMTP_PORT     = int(os.environ.get('NONCEY_TEST_SMTP_PORT', '25'))
MAIL_CONF     = os.environ.get('NONCEY_TEST_MAIL_CONF', '/etc/noncey/noncey.conf')
POLL_TIMEOUT  = 15    # seconds to wait for Postfix delivery
POLL_INTERVAL = 0.5


def _read_prod_conf() -> tuple[str, str]:
    """Read domain and db_path from the noncey.conf used by the Postfix transport."""
    cfg = configparser.ConfigParser()
    cfg.read(MAIL_CONF)
    domain  = cfg.get('general', 'domain',   fallback='')
    db_path = cfg.get('paths',   'db_path',  fallback='/opt/noncey/noncey.db')
    return domain, db_path


def _send(nonce_value: str, domain: str) -> None:
    body = (
        f"This is an automated noncey smoke-test message.\n\n"
        f"Your one-time code: "
        f"{TEST_START_MARKER}{nonce_value}{TEST_END_MARKER}\n"
    )
    msg            = MIMEText(body)
    msg['From']    = TEST_SENDER
    msg['To']      = f'nonce-{TEST_USERNAME}@{domain}'
    msg['Subject'] = 'noncey smoke test'

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
        smtp.sendmail(TEST_SENDER, [msg['To']], msg.as_string())


@pytest.fixture(scope='module')
def prod_seed():
    """
    Seed the _test_ user + provider + matcher into the PRODUCTION DB for the
    duration of the mail test module, then remove them on teardown.

    Uses CASCADE: deleting the user row removes all associated rows.
    """
    domain, db_path = _read_prod_conf()
    if not domain:
        pytest.skip(f'could not read domain from {MAIL_CONF}')
    conn    = _open_db(db_path)
    pw_hash = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt()).decode()

    cur = conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (TEST_USERNAME, pw_hash),
    )
    user_id = cur.lastrowid

    cur = conn.execute(
        "INSERT INTO providers "
        "  (user_id, tag, extract_mode, nonce_start_marker, nonce_end_marker) "
        "VALUES (?, ?, 'markers', ?, ?)",
        (user_id, TEST_PROVIDER_TAG, TEST_START_MARKER, TEST_END_MARKER),
    )
    provider_id = cur.lastrowid

    conn.execute(
        "INSERT INTO provider_matchers (provider_id, sender_email, subject_pattern) "
        "VALUES (?, ?, ?)",
        (provider_id, TEST_SENDER, TEST_SUBJECT_PATTERN),
    )
    conn.commit()
    conn.close()

    yield {'user_id': user_id, 'db_path': db_path, 'domain': domain}

    conn = _open_db(db_path)
    conn.execute("DELETE FROM users WHERE username = ?", (TEST_USERNAME,))
    conn.commit()
    conn.close()


def test_mail_delivery_end_to_end(prod_seed):
    """
    Send email via SMTP → Postfix → nonce-pipe → ingest.py → production DB.
    Verifies the nonce appears in the DB within POLL_TIMEOUT seconds.
    """
    nonce_value = 'MAILSMOKE-' + secrets.token_hex(4).upper()
    _send(nonce_value, prod_seed['domain'])

    nonce_id = None
    deadline = time.monotonic() + POLL_TIMEOUT
    while time.monotonic() < deadline:
        conn = _open_db(prod_seed['db_path'])
        row  = conn.execute(
            "SELECT id FROM nonces WHERE user_id = ? AND nonce_value = ?",
            (prod_seed['user_id'], nonce_value),
        ).fetchone()
        conn.close()
        if row:
            nonce_id = row[0]
            break
        time.sleep(POLL_INTERVAL)

    # Cleanup regardless of outcome.
    if nonce_id is not None:
        conn = _open_db(prod_seed['db_path'])
        conn.execute("DELETE FROM nonces WHERE id = ?", (nonce_id,))
        conn.commit()
        conn.close()

    assert nonce_id is not None, (
        f"Nonce {nonce_value!r} not found in production DB ({prod_seed['db_path']!r})"
        f" after {POLL_TIMEOUT}s.\n"
        f"Mail was sent to: nonce-{TEST_USERNAME}@{prod_seed['domain']}\n"
        "Diagnostics: journalctl -u postfix -n 50"
    )

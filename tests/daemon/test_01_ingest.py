"""
test_01_ingest — Direct ingest pipe tests.

Calls ingest.py as a subprocess (exactly as Postfix would), passes a
synthetic .eml on stdin, then checks the SQLite DB directly.

No running Flask instance or mail server required.
"""

import os
import secrets
import sqlite3
import subprocess
import sys
from pathlib import Path

from conftest import DAEMON_DIR, TEST_DOMAIN, TEST_USERNAME, _open_db

EML_TEMPLATE  = (Path(__file__).parent.parent / 'fixtures' / 'sample_otp.eml').read_text()
INGEST_SCRIPT = DAEMON_DIR / 'ingest.py'


def _run_ingest(recipient: str, eml: bytes, conf_path) -> subprocess.CompletedProcess:
    env = {**os.environ, 'NONCEY_CONF': str(conf_path)}
    return subprocess.run(
        [sys.executable, str(INGEST_SCRIPT), recipient],
        input=eml,
        capture_output=True,
        env=env,
        timeout=15,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_ingest_writes_nonce_to_db(tmp_env, seed_data):
    """ingest.py extracts the nonce and inserts a row into the nonces table."""
    nonce_value = 'SMOKE-' + secrets.token_hex(4).upper()
    eml         = EML_TEMPLATE.format(nonce=nonce_value).encode()
    recipient   = f'nonce-{TEST_USERNAME}@{TEST_DOMAIN}'

    result = _run_ingest(recipient, eml, tmp_env['conf_path'])
    assert result.returncode == 0, result.stderr.decode()

    conn = _open_db(tmp_env['db_path'])
    row  = conn.execute(
        "SELECT nonce_value FROM nonces "
        "WHERE  user_id = ? "
        "ORDER  BY received_at DESC LIMIT 1",
        (seed_data['user_id'],),
    ).fetchone()
    conn.close()

    assert row is not None, 'no nonce row found after ingest'
    assert row['nonce_value'] == nonce_value


def test_ingest_archives_eml(tmp_env, seed_data):
    """ingest.py writes a .eml file to the archive directory."""
    nonce_value = 'ARCHIVE-' + secrets.token_hex(4).upper()
    eml         = EML_TEMPLATE.format(nonce=nonce_value).encode()
    recipient   = f'nonce-{TEST_USERNAME}@{TEST_DOMAIN}'

    result = _run_ingest(recipient, eml, tmp_env['conf_path'])
    assert result.returncode == 0, result.stderr.decode()

    archive_dir = tmp_env['archive_path'] / TEST_USERNAME
    eml_files   = list(archive_dir.glob('*.eml'))
    assert len(eml_files) > 0, 'no .eml file found in archive after ingest'


def test_ingest_unknown_user_exits_67(tmp_env):
    """ingest.py exits EX_NOUSER (67) when the recipient user does not exist."""
    eml       = EML_TEMPLATE.format(nonce='IGNORED').encode()
    recipient = f'nonce-nonexistent-xyz@{TEST_DOMAIN}'

    result = _run_ingest(recipient, eml, tmp_env['conf_path'])
    assert result.returncode == 67


def test_ingest_unmatched_sender_exits_0(tmp_env, seed_data):
    """
    ingest.py exits 0 for an email from an unrecognised sender.
    The email is archived but no nonce row is inserted.
    """
    eml = (
        "From: unknown-sender@example.com\r\n"
        f"To: nonce-{TEST_USERNAME}@{TEST_DOMAIN}\r\n"
        "Subject: something completely unrelated\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain\r\n"
        "\r\n"
        "No recognised markers here.\r\n"
    ).encode()
    recipient = f'nonce-{TEST_USERNAME}@{TEST_DOMAIN}'

    conn_before = _open_db(tmp_env['db_path'])
    count_before = conn_before.execute(
        "SELECT COUNT(*) FROM nonces WHERE user_id = ?",
        (seed_data['user_id'],),
    ).fetchone()[0]
    conn_before.close()

    result = _run_ingest(recipient, eml, tmp_env['conf_path'])
    assert result.returncode == 0

    conn_after  = _open_db(tmp_env['db_path'])
    count_after = conn_after.execute(
        "SELECT COUNT(*) FROM nonces WHERE user_id = ?",
        (seed_data['user_id'],),
    ).fetchone()[0]
    conn_after.close()

    assert count_after == count_before, 'nonce was inserted for unmatched sender'


def test_ingest_bad_recipient_format_exits_67(tmp_env):
    """ingest.py exits 67 when the recipient local part lacks the 'nonce-' prefix."""
    eml       = EML_TEMPLATE.format(nonce='IGNORED').encode()
    recipient = f'notanonce@{TEST_DOMAIN}'

    result = _run_ingest(recipient, eml, tmp_env['conf_path'])
    assert result.returncode == 67

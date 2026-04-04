"""
Shared fixtures for the noncey test suite.

The temporary environment (config file, SQLite DB, archive dir) is created at
module load time so that NONCEY_CONF is set before any daemon module is
imported.  A session-scoped fixture seeds the test user/provider/matcher and
tears them down when the suite finishes.

Test identity is isolated by using the reserved username '_test_' (underscore
prefix is visually distinct and valid per noncey username rules).  All test
data is cleaned up via SQLite CASCADE on the users row, so running the suite
against a production DB is safe.
"""

import atexit
import configparser
import os
import secrets
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
import pytest
from flask import url_for

# ── Path constants ─────────────────────────────────────────────────────────────

TESTS_DIR  = Path(__file__).parent
NONCEY_DIR = TESTS_DIR.parent
DAEMON_DIR = NONCEY_DIR.parent / 'noncey.daemon'
SCHEMA_SQL = DAEMON_DIR / 'schema.sql'

# Daemon modules are imported inside fixtures; sys.path must be set first.
sys.path.insert(0, str(DAEMON_DIR))
sys.path.insert(0, str(TESTS_DIR))   # so test files can 'from conftest import ...'

# ── Test identity constants ────────────────────────────────────────────────────

TEST_USERNAME        = '_test_'
TEST_PASSWORD        = 'noncey-smoke-test-pw-do-not-use'
TEST_PROVIDER_TAG    = 'smoke-test'
TEST_SENDER          = 'noncey-test@example.com'
TEST_SUBJECT_PATTERN = r'noncey smoke test'
TEST_START_MARKER    = 'NONCE-START:'
TEST_END_MARKER      = ':NONCE-END'
TEST_DOMAIN          = 'nonces.example.com'

# ── Temp environment ──────────────────────────────────────────────────────────
# Created at module load time so NONCEY_CONF is set before any app import.

_tmp_dir      = Path(tempfile.mkdtemp(prefix='noncey_test_'))
_db_path      = _tmp_dir / 'noncey.db'
_archive_path = _tmp_dir / 'archive'
_conf_path    = _tmp_dir / 'noncey.conf'

_archive_path.mkdir()
atexit.register(shutil.rmtree, str(_tmp_dir), ignore_errors=True)


def _write_conf() -> None:
    cfg = configparser.ConfigParser()
    cfg['general'] = {
        'domain':              TEST_DOMAIN,
        'admin_domain':        'admin.example.com',
        'nonce_lifetime_h':    '2',
        'archive_retention_d': '30',
        'flask_port':          '15000',
        'secret_key':          'test-secret-key-noncey-smoke-do-not-use',
    }
    cfg['mysql'] = {
        'host': 'localhost', 'user': 'unused',
        'password': 'unused', 'database': 'unused',
    }
    cfg['tls']   = {'cert': '/dev/null', 'key': '/dev/null'}
    cfg['paths'] = {
        'install_dir':  str(_tmp_dir),
        'db_path':      str(_db_path),
        'archive_path': str(_archive_path),
    }
    with open(_conf_path, 'w') as f:
        cfg.write(f)


_write_conf()
os.environ['NONCEY_CONF'] = str(_conf_path)

_conn = sqlite3.connect(str(_db_path))
_conn.executescript(SCHEMA_SQL.read_text())
_conn.commit()
_conn.close()


# ── DB helper (used by fixtures and test files) ───────────────────────────────

def _open_db(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope='session')
def tmp_env():
    """Paths to the temp environment components."""
    return {
        'base':         _tmp_dir,
        'db_path':      _db_path,
        'archive_path': _archive_path,
        'conf_path':    _conf_path,
    }


@pytest.fixture(scope='session')
def seed_data(tmp_env):
    """
    Insert the test user, provider and matcher into the DB.
    Teardown deletes the user row; CASCADE removes all associated data.
    """
    conn    = _open_db(tmp_env['db_path'])
    pw_hash = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt()).decode()

    cur = conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (TEST_USERNAME, pw_hash),
    )
    user_id = cur.lastrowid

    cur = conn.execute(
        "INSERT INTO providers "
        "  (user_id, tag, extract_mode, nonce_start_marker, nonce_end_marker) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, TEST_PROVIDER_TAG, 'markers', TEST_START_MARKER, TEST_END_MARKER),
    )
    provider_id = cur.lastrowid

    conn.execute(
        "INSERT INTO provider_matchers (provider_id, sender_email, subject_pattern) "
        "VALUES (?, ?, ?)",
        (provider_id, TEST_SENDER, TEST_SUBJECT_PATTERN),
    )
    conn.commit()
    conn.close()

    yield {'user_id': user_id, 'provider_id': provider_id}

    conn = _open_db(tmp_env['db_path'])
    conn.execute("DELETE FROM users WHERE username = ?", (TEST_USERNAME,))
    conn.commit()
    conn.close()


@pytest.fixture(scope='session')
def flask_app(tmp_env, seed_data):
    """Flask application wired to the temp DB, using the Flask test client."""
    import db as db_module
    db_module._cfg = None   # force re-read from NONCEY_CONF

    from app import app
    app.config['TESTING'] = True
    yield app

    db_module._cfg = None


@pytest.fixture(scope='session')
def url(flask_app):
    """Resolve Flask endpoint names to URL paths via url_for().

    Use this instead of hardcoding paths in tests — if a route moves in
    admin.py or app.py, url_for() picks up the change automatically.

    Usage::

        def test_something(client, url):
            resp = client.get(url('admin.dashboard'))
    """
    def resolve(endpoint, **kwargs):
        with flask_app.test_request_context():
            return url_for(endpoint, **kwargs)
    return resolve


@pytest.fixture
def client(flask_app):
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def auth_token(client):
    """A valid JWT for TEST_USERNAME, valid for the duration of one test."""
    resp = client.post('/api/auth/login', json={
        'username': TEST_USERNAME,
        'password': TEST_PASSWORD,
    })
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()['token']


@pytest.fixture
def seeded_nonce(tmp_env, seed_data):
    """
    Insert a nonce directly into the DB for API tests.
    Cleaned up on teardown even if the test already deleted it.
    """
    value   = 'FIXTURE-' + secrets.token_hex(4).upper()
    now     = datetime.now(timezone.utc)
    expires = now + timedelta(hours=2)

    conn = _open_db(tmp_env['db_path'])
    cur  = conn.execute(
        "INSERT INTO nonces "
        "  (user_id, provider_id, nonce_value, received_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (seed_data['user_id'], seed_data['provider_id'],
         value, now.isoformat(), expires.isoformat()),
    )
    nonce_id = cur.lastrowid
    conn.commit()
    conn.close()

    yield {'id': nonce_id, 'value': value}

    conn = _open_db(tmp_env['db_path'])
    conn.execute("DELETE FROM nonces WHERE id = ?", (nonce_id,))
    conn.commit()
    conn.close()

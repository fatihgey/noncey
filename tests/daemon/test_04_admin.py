"""
test_04_admin — Server UI: access, authentication, and user management.

All routes sit under /auth/ and require a Flask session cookie
(managed entirely by Flask — no Apache BasicAuth).
Admin-only routes (/auth/admin/) additionally require is_admin=1.

URLs are resolved via the url() fixture (url_for under the hood) so that
path changes in admin.py never require updates here.
"""

import bcrypt as _bcrypt
import pytest

from conftest import TEST_PASSWORD, TEST_USERNAME, _open_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def logged_in_client(client, url):
    """Test client with an active session for TEST_USERNAME."""
    client.post(url('admin.auth_login'), data={
        'username': TEST_USERNAME,
        'password': TEST_PASSWORD,
    })
    yield client


@pytest.fixture
def admin_client(client, url, tmp_env, seed_data):
    """Test client logged in as TEST_USERNAME with is_admin=1."""
    conn = _open_db(tmp_env['db_path'])
    conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (seed_data['user_id'],))
    conn.commit()
    conn.close()

    client.post(url('admin.auth_login'), data={
        'username': TEST_USERNAME,
        'password': TEST_PASSWORD,
    })
    yield client

    conn = _open_db(tmp_env['db_path'])
    conn.execute("UPDATE users SET is_admin=0 WHERE id=?", (seed_data['user_id'],))
    conn.commit()
    conn.close()


# ── Server UI Authentication ──────────────────────────────────────────────────

def test_login_returns_session(client, url):
    resp = client.post(url('admin.auth_login'), data={
        'username': TEST_USERNAME,
        'password': TEST_PASSWORD,
    })
    assert resp.status_code == 302
    # Confirm session is active: protected route now returns 200.
    assert client.get(url('admin.dashboard')).status_code == 200


def test_login_wrong_password_rejected(client, url):
    resp = client.post(url('admin.auth_login'), data={
        'username': TEST_USERNAME,
        'password': 'wrong-password',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Invalid' in resp.data


def test_login_unknown_user_rejected(client, url):
    resp = client.post(url('admin.auth_login'), data={
        'username': 'nonexistent-xyz',
        'password': 'whatever',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Invalid' in resp.data


def test_dashboard_requires_auth(client, url):
    resp = client.get(url('admin.dashboard'))
    assert resp.status_code == 302
    assert 'login' in resp.headers['Location']


def test_logout_clears_session(logged_in_client, url):
    resp = logged_in_client.post(url('admin.auth_logout'))
    assert resp.status_code == 302
    # Session is now gone: dashboard redirects to login again.
    assert logged_in_client.get(url('admin.dashboard')).status_code == 302


# ── Dashboard ─────────────────────────────────────────────────────────────────

def test_dashboard_ok(logged_in_client, url):
    assert logged_in_client.get(url('admin.dashboard')).status_code == 200


def test_dashboard_lists_test_user(logged_in_client, url):
    resp = logged_in_client.get(url('admin.dashboard'))
    assert TEST_USERNAME.encode() in resp.data


# ── User Management (Admin) ───────────────────────────────────────────────────

def test_create_user_success(admin_client, url, tmp_env):
    resp = admin_client.post(url('admin.admin_user_new'), data={
        'username':  'uinew',
        'password':  'strongpassword1',
        'password2': 'strongpassword1',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'uinew' in resp.data

    conn = _open_db(tmp_env['db_path'])
    conn.execute("DELETE FROM users WHERE username=?", ('uinew',))
    conn.commit()
    conn.close()


def test_create_user_password_mismatch(admin_client, url):
    resp = admin_client.post(url('admin.admin_user_new'), data={
        'username':  'mismatch',
        'password':  'aaa',
        'password2': 'bbb',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'do not match' in resp.data


def test_create_user_empty_password(admin_client, url):
    resp = admin_client.post(url('admin.admin_user_new'), data={
        'username':  'emptypass',
        'password':  '',
        'password2': '',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'not be empty' in resp.data


def test_create_duplicate_user(admin_client, url, tmp_env):
    admin_client.post(url('admin.admin_user_new'), data={
        'username': 'duptest', 'password': 'pw1234', 'password2': 'pw1234',
    })
    resp = admin_client.post(url('admin.admin_user_new'), data={
        'username': 'duptest', 'password': 'pw1234', 'password2': 'pw1234',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'already exists' in resp.data

    conn = _open_db(tmp_env['db_path'])
    conn.execute("DELETE FROM users WHERE username=?", ('duptest',))
    conn.commit()
    conn.close()


def test_edit_user(admin_client, url, tmp_env):
    admin_client.post(url('admin.admin_user_new'), data={
        'username': 'editme', 'password': 'pw1234', 'password2': 'pw1234',
    })
    conn = _open_db(tmp_env['db_path'])
    row  = conn.execute("SELECT id FROM users WHERE username=?", ('editme',)).fetchone()
    conn.close()
    assert row, 'user was not created'

    resp = admin_client.post(
        url('admin.admin_user_edit', user_id=row[0]),
        data={'email': 'edited@example.com', 'is_admin': ''},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b'updated' in resp.data.lower()

    conn = _open_db(tmp_env['db_path'])
    updated = conn.execute("SELECT email FROM users WHERE id=?", (row[0],)).fetchone()
    conn.execute("DELETE FROM users WHERE id=?", (row[0],))
    conn.commit()
    conn.close()
    assert updated['email'] == 'edited@example.com'


def test_delete_user(admin_client, url, tmp_env):
    admin_client.post(url('admin.admin_user_new'), data={
        'username': 'delme', 'password': 'pw1234', 'password2': 'pw1234',
    })
    conn = _open_db(tmp_env['db_path'])
    row  = conn.execute("SELECT id FROM users WHERE username=?", ('delme',)).fetchone()
    conn.close()
    assert row, 'user was not created'

    resp = admin_client.post(
        url('admin.admin_user_delete', user_id=row[0]),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b'deleted' in resp.data.lower()

    conn = _open_db(tmp_env['db_path'])
    gone = conn.execute("SELECT id FROM users WHERE username=?", ('delme',)).fetchone()
    conn.close()
    assert gone is None


# ── Account (Self-service) ────────────────────────────────────────────────────

def test_change_password_success(logged_in_client, url, tmp_env, seed_data):
    resp = logged_in_client.post(url('admin.account_settings'), data={
        'current_password': TEST_PASSWORD,
        'password':         'new-test-pw-99',
        'password2':        'new-test-pw-99',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Password changed' in resp.data

    # Restore original password so subsequent tests can still log in.
    orig_hash = _bcrypt.hashpw(TEST_PASSWORD.encode(), _bcrypt.gensalt()).decode()
    conn = _open_db(tmp_env['db_path'])
    conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                 (orig_hash, seed_data['user_id']))
    conn.commit()
    conn.close()


def test_change_password_wrong_current_rejected(logged_in_client, url):
    resp = logged_in_client.post(url('admin.account_settings'), data={
        'current_password': 'definitely-wrong',
        'password':         'new-pw',
        'password2':        'new-pw',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'incorrect' in resp.data.lower()

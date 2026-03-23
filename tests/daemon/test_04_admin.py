"""
test_04_admin — Admin Blueprint CRUD via Flask test client.

The admin Blueprint has no auth layer (Apache handles that in production),
so all routes are directly accessible from the test client.

Each test that creates DB rows is responsible for cleaning them up, keeping
tests independent of execution order.
"""

import pytest

from conftest import TEST_USERNAME, _open_db


# ── Dashboard ─────────────────────────────────────────────────────────────────

def test_dashboard_ok(client):
    resp = client.get('/noncey/')
    assert resp.status_code == 200


def test_dashboard_trailing_slash_redirect(client):
    resp = client.get('/noncey')
    # Either 200 or a redirect to /noncey/ is acceptable.
    assert resp.status_code in (200, 301, 308)


def test_dashboard_lists_test_user(client):
    resp = client.get('/noncey/')
    assert TEST_USERNAME.encode() in resp.data


# ── User create ───────────────────────────────────────────────────────────────

def test_create_user_success(client, tmp_env):
    resp = client.post('/noncey/users/new', data={
        'username':  '_ui_new_',
        'password':  'strongpassword1',
        'password2': 'strongpassword1',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'_ui_new_' in resp.data

    conn = _open_db(tmp_env['db_path'])
    conn.execute("DELETE FROM users WHERE username = ?", ('_ui_new_',))
    conn.commit()
    conn.close()


def test_create_user_password_mismatch(client):
    resp = client.post('/noncey/users/new', data={
        'username':  '_mismatch_',
        'password':  'aaa',
        'password2': 'bbb',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'do not match' in resp.data


def test_create_user_empty_password(client):
    resp = client.post('/noncey/users/new', data={
        'username':  '_emptypass_',
        'password':  '',
        'password2': '',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'empty' in resp.data.lower() or b'required' in resp.data.lower()


def test_create_duplicate_user(client, tmp_env):
    # First creation succeeds.
    client.post('/noncey/users/new', data={
        'username': '_dup_test_', 'password': 'pw', 'password2': 'pw',
    })
    # Second creation for the same username must be rejected.
    resp = client.post('/noncey/users/new', data={
        'username': '_dup_test_', 'password': 'pw', 'password2': 'pw',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'already exists' in resp.data

    conn = _open_db(tmp_env['db_path'])
    conn.execute("DELETE FROM users WHERE username = ?", ('_dup_test_',))
    conn.commit()
    conn.close()


# ── User delete ───────────────────────────────────────────────────────────────

def test_delete_user(client, tmp_env):
    # Create a user via the UI, then delete it via the UI.
    client.post('/noncey/users/new', data={
        'username': '_del_me_', 'password': 'pw', 'password2': 'pw',
    })
    conn = _open_db(tmp_env['db_path'])
    row  = conn.execute(
        "SELECT id FROM users WHERE username = ?", ('_del_me_',)
    ).fetchone()
    conn.close()
    assert row, 'user was not created'

    resp = client.post(f'/noncey/users/{row[0]}/delete', follow_redirects=True)
    assert resp.status_code == 200
    assert b'deleted' in resp.data.lower()

    conn = _open_db(tmp_env['db_path'])
    gone = conn.execute(
        "SELECT id FROM users WHERE username = ?", ('_del_me_',)
    ).fetchone()
    conn.close()
    assert gone is None


# ── Provider CRUD ─────────────────────────────────────────────────────────────

@pytest.fixture
def provider_owner(tmp_env):
    """A dedicated user for provider CRUD tests; deleted on teardown."""
    import bcrypt
    pw = bcrypt.hashpw(b'pw', bcrypt.gensalt()).decode()
    conn = _open_db(tmp_env['db_path'])
    cur  = conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        ('_prov_owner_', pw),
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()
    yield user_id
    conn = _open_db(tmp_env['db_path'])
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def test_create_provider(client, provider_owner):
    resp = client.post(
        f'/noncey/users/{provider_owner}/providers/new',
        data={
            'tag':                'smoke-prov',
            'nonce_start_marker': 'CODE:',
            'nonce_end_marker':   ':END',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b'smoke-prov' in resp.data


def test_create_provider_missing_tag_rejected(client, provider_owner):
    resp = client.post(
        f'/noncey/users/{provider_owner}/providers/new',
        data={'tag': '', 'nonce_start_marker': 'X:'},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b'required' in resp.data.lower()


def test_delete_provider(client, provider_owner, tmp_env):
    # Create provider, get its ID, then delete it.
    client.post(
        f'/noncey/users/{provider_owner}/providers/new',
        data={'tag': 'del-prov', 'nonce_start_marker': 'X:'},
    )
    conn = _open_db(tmp_env['db_path'])
    row  = conn.execute(
        "SELECT id FROM providers WHERE user_id = ? AND tag = ?",
        (provider_owner, 'del-prov'),
    ).fetchone()
    conn.close()
    assert row

    resp = client.post(
        f'/noncey/users/{provider_owner}/providers/{row[0]}/delete',
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b'del-prov' not in resp.data


# ── Matcher CRUD ──────────────────────────────────────────────────────────────

@pytest.fixture
def provider_with_matchers(client, provider_owner, tmp_env):
    """Create a provider; yield its ID; teardown is handled by provider_owner CASCADE."""
    client.post(
        f'/noncey/users/{provider_owner}/providers/new',
        data={'tag': 'matcher-test', 'nonce_start_marker': 'OTP:'},
    )
    conn = _open_db(tmp_env['db_path'])
    row  = conn.execute(
        "SELECT id FROM providers WHERE user_id = ? AND tag = ?",
        (provider_owner, 'matcher-test'),
    ).fetchone()
    conn.close()
    assert row
    yield row[0]


def test_add_matcher(client, provider_owner, provider_with_matchers):
    resp = client.post(
        f'/noncey/users/{provider_owner}/providers/{provider_with_matchers}/matchers/new',
        data={'sender_email': 'smoke@example.com', 'subject_pattern': ''},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b'smoke@example.com' in resp.data


def test_add_matcher_both_empty_rejected(client, provider_owner, provider_with_matchers):
    resp = client.post(
        f'/noncey/users/{provider_owner}/providers/{provider_with_matchers}/matchers/new',
        data={'sender_email': '', 'subject_pattern': ''},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b'At least one' in resp.data


def test_delete_matcher(client, provider_owner, provider_with_matchers, tmp_env):
    client.post(
        f'/noncey/users/{provider_owner}/providers/{provider_with_matchers}/matchers/new',
        data={'sender_email': 'del@example.com', 'subject_pattern': ''},
    )
    conn = _open_db(tmp_env['db_path'])
    row  = conn.execute(
        "SELECT id FROM provider_matchers "
        "WHERE provider_id = ? AND sender_email = ?",
        (provider_with_matchers, 'del@example.com'),
    ).fetchone()
    conn.close()
    assert row

    resp = client.post(
        f'/noncey/users/{provider_owner}/providers/'
        f'{provider_with_matchers}/matchers/{row[0]}/delete',
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b'del@example.com' not in resp.data

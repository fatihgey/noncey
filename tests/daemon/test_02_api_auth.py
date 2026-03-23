"""
test_02_api_auth — REST authentication endpoints.

Uses the Flask test client; no running server or mail delivery required.
"""

from conftest import TEST_PASSWORD, TEST_USERNAME


# ── Login ─────────────────────────────────────────────────────────────────────

def test_login_returns_token(client):
    resp = client.post('/api/auth/login', json={
        'username': TEST_USERNAME,
        'password': TEST_PASSWORD,
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'token' in data
    assert 'expires_at' in data


def test_login_wrong_password_rejected(client):
    resp = client.post('/api/auth/login', json={
        'username': TEST_USERNAME,
        'password': 'definitely-wrong',
    })
    assert resp.status_code == 401


def test_login_unknown_user_rejected(client):
    resp = client.post('/api/auth/login', json={
        'username': 'nobody-xyz',
        'password': 'anything',
    })
    assert resp.status_code == 401


def test_login_missing_fields_rejected(client):
    resp = client.post('/api/auth/login', json={})
    assert resp.status_code == 400


def test_nonces_endpoint_requires_auth(client):
    resp = client.get('/api/nonces')
    assert resp.status_code == 401


def test_invalid_bearer_token_rejected(client):
    resp = client.get('/api/nonces',
                      headers={'Authorization': 'Bearer not.a.valid.jwt'})
    assert resp.status_code == 401


# ── Logout ────────────────────────────────────────────────────────────────────

def test_logout_returns_204(client, auth_token):
    resp = client.post('/api/auth/logout',
                       headers={'Authorization': f'Bearer {auth_token}'})
    assert resp.status_code == 204


def test_logout_invalidates_token(client, auth_token):
    client.post('/api/auth/logout',
                headers={'Authorization': f'Bearer {auth_token}'})

    # The same token must now be rejected.
    resp = client.get('/api/nonces',
                      headers={'Authorization': f'Bearer {auth_token}'})
    assert resp.status_code == 401


def test_logout_requires_auth(client):
    resp = client.post('/api/auth/logout')
    assert resp.status_code == 401

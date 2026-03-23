"""
test_03_api_nonces — GET /api/nonces and DELETE /api/nonces/<id>.

The `seeded_nonce` fixture inserts a nonce directly into the DB (no email
required) and cleans up on teardown, so each test starts with a known state.
"""

from conftest import TEST_PROVIDER_TAG


def _auth(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


# ── GET /api/nonces ───────────────────────────────────────────────────────────

def test_get_nonces_returns_list(client, auth_token):
    resp = client.get('/api/nonces', headers=_auth(auth_token))
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


def test_get_nonces_includes_seeded_nonce(client, auth_token, seeded_nonce):
    resp   = client.get('/api/nonces', headers=_auth(auth_token))
    nonces = resp.get_json()

    found = next((n for n in nonces if n['id'] == seeded_nonce['id']), None)
    assert found is not None, 'seeded nonce not returned by GET /api/nonces'
    assert found['nonce_value']  == seeded_nonce['value']
    assert found['provider_tag'] == TEST_PROVIDER_TAG
    assert 'age_seconds' in found
    assert 'expires_at'  in found


def test_get_nonces_requires_auth(client):
    resp = client.get('/api/nonces')
    assert resp.status_code == 401


def test_get_nonces_only_returns_own_data(client, auth_token, seeded_nonce):
    """All returned nonces must have expected fields (spot-check isolation)."""
    nonces = client.get('/api/nonces', headers=_auth(auth_token)).get_json()
    for n in nonces:
        assert 'id'           in n
        assert 'nonce_value'  in n
        assert 'provider_tag' in n
        assert 'age_seconds'  in n


# ── DELETE /api/nonces/<id> ───────────────────────────────────────────────────

def test_delete_nonce_returns_204(client, auth_token, seeded_nonce):
    resp = client.delete(f'/api/nonces/{seeded_nonce["id"]}',
                         headers=_auth(auth_token))
    assert resp.status_code == 204


def test_deleted_nonce_absent_from_list(client, auth_token, seeded_nonce):
    client.delete(f'/api/nonces/{seeded_nonce["id"]}', headers=_auth(auth_token))

    nonces = client.get('/api/nonces', headers=_auth(auth_token)).get_json()
    ids    = [n['id'] for n in nonces]
    assert seeded_nonce['id'] not in ids


def test_delete_nonexistent_nonce_returns_404(client, auth_token):
    resp = client.delete('/api/nonces/999999', headers=_auth(auth_token))
    assert resp.status_code == 404


def test_delete_nonce_requires_auth(client, seeded_nonce):
    resp = client.delete(f'/api/nonces/{seeded_nonce["id"]}')
    assert resp.status_code == 401

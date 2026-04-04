"""
test_07_api_configs — REST API: config sync (pull + push).

Tests GET /api/configs, POST /api/configs/<id>/prompt, and
POST /api/configs/<id>/client-test — the endpoints the Chrome extension uses
to synchronise configuration data with the daemon.
"""

import json

import pytest

from conftest import _open_db


def _auth(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def valid_config(tmp_env, seed_data):
    """Private config at status=valid with channel, header, prompt, and activated=1."""
    user_id = seed_data['user_id']
    prompt  = json.dumps({'url': 'https://example.com', 'url_match': 'prefix',
                          'selector': '#otp'})
    conn    = _open_db(tmp_env['db_path'])
    cur     = conn.execute(
        "INSERT INTO configurations "
        "  (owner_id, name, version, status, visibility, prompt, activated) "
        "VALUES (?, 'api-cfg', '-1', 'valid', 'private', ?, 1)",
        (user_id, prompt),
    )
    config_id   = cur.lastrowid
    cur         = conn.execute(
        "INSERT INTO providers "
        "  (user_id, config_id, tag, extract_mode, nonce_start_marker) "
        "VALUES (?, ?, 'api-ch', 'markers', 'OTP:')",
        (user_id, config_id),
    )
    provider_id = cur.lastrowid
    conn.execute(
        "INSERT INTO provider_matchers (provider_id, sender_email) "
        "VALUES (?, 'api@example.com')",
        (provider_id,),
    )
    conn.commit()
    conn.close()

    yield {'config_id': config_id, 'provider_id': provider_id}

    conn = _open_db(tmp_env['db_path'])
    conn.execute("DELETE FROM configurations WHERE id=?", (config_id,))
    conn.commit()
    conn.close()


@pytest.fixture
def public_sub_config(tmp_env, seed_data):
    """Public config owned by a second user, subscribed to by TEST_USERNAME."""
    user_id = seed_data['user_id']
    prompt  = json.dumps({'url': 'https://public.example.com', 'url_match': 'prefix',
                          'selector': '#pw'})
    conn    = _open_db(tmp_env['db_path'])

    conn.execute("DELETE FROM users WHERE username='api-owner2'")
    cur       = conn.execute(
        "INSERT INTO users (username, password_hash) VALUES ('api-owner2', 'x')"
    )
    owner2_id = cur.lastrowid

    cur         = conn.execute(
        "INSERT INTO configurations "
        "  (owner_id, name, version, status, visibility, prompt) "
        "VALUES (?, 'pub-cfg', '202401-01', 'valid', 'public', ?)",
        (owner2_id, prompt),
    )
    config_id   = cur.lastrowid
    cur         = conn.execute(
        "INSERT INTO providers "
        "  (user_id, config_id, tag, extract_mode, nonce_start_marker) "
        "VALUES (?, ?, 'pub-ch', 'markers', 'CODE:')",
        (owner2_id, config_id),
    )
    conn.execute(
        "INSERT INTO provider_matchers (provider_id, sender_email) "
        "VALUES (?, 'pub@example.com')",
        (cur.lastrowid,),
    )
    conn.execute(
        "INSERT INTO subscriptions (user_id, config_id) VALUES (?, ?)",
        (user_id, config_id),
    )
    conn.commit()
    conn.close()

    yield config_id

    conn = _open_db(tmp_env['db_path'])
    conn.execute("DELETE FROM users WHERE id=?", (owner2_id,))  # cascades to config + sub
    conn.commit()
    conn.close()


# ── Pull — GET /api/configs ───────────────────────────────────────────────────

def test_get_configs_returns_list(client, auth_token):
    resp = client.get('/api/configs', headers=_auth(auth_token))
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


def test_get_configs_includes_own_valid_config(client, auth_token, valid_config):
    configs = client.get('/api/configs', headers=_auth(auth_token)).get_json()
    found   = next((c for c in configs if c['id'] == valid_config['config_id']), None)
    assert found is not None, 'own valid config not returned'
    assert found['name']         == 'api-cfg'
    assert found['status']       == 'valid'
    assert found['is_owned']     is True
    assert found['activated']    is True
    assert found['prompt']       is not None
    assert 'provider_tags'       in found
    assert 'api-ch'              in found['provider_tags']


def test_get_configs_includes_subscribed_public_config(
        client, auth_token, public_sub_config):
    configs = client.get('/api/configs', headers=_auth(auth_token)).get_json()
    found   = next((c for c in configs if c['id'] == public_sub_config), None)
    assert found is not None, 'subscribed public config not returned'
    assert found['visibility'] == 'public'
    assert found['is_owned']   is False
    assert found['prompt']     is not None
    assert 'provider_tags'     in found


def test_get_configs_only_returns_own_and_subscribed(client, auth_token, tmp_env):
    """A private config owned by a different user must not appear in the response."""
    conn = _open_db(tmp_env['db_path'])
    conn.execute("DELETE FROM users WHERE username='api-iso-user'")
    cur  = conn.execute(
        "INSERT INTO users (username, password_hash) VALUES ('api-iso-user', 'x')"
    )
    other_uid = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO configurations "
        "  (owner_id, name, version, status, visibility) "
        "VALUES (?, 'isolated-cfg', '-1', 'valid', 'private')",
        (other_uid,),
    )
    other_config_id = cur.lastrowid
    conn.commit()
    conn.close()

    try:
        configs = client.get('/api/configs', headers=_auth(auth_token)).get_json()
        assert other_config_id not in [c['id'] for c in configs]
    finally:
        conn = _open_db(tmp_env['db_path'])
        conn.execute("DELETE FROM users WHERE id=?", (other_uid,))
        conn.commit()
        conn.close()


def test_get_configs_requires_auth(client):
    resp = client.get('/api/configs')
    assert resp.status_code == 401


# ── Push — POST /api/configs/<id>/prompt ─────────────────────────────────────

def test_push_prompt_stores_url_and_selector(client, auth_token, tmp_env, seed_data):
    conn = _open_db(tmp_env['db_path'])
    cur  = conn.execute(
        "INSERT INTO configurations "
        "  (owner_id, name, version, status, visibility) "
        "VALUES (?, 'prompt-store', '-1', 'valid', 'private')",
        (seed_data['user_id'],),
    )
    config_id = cur.lastrowid
    conn.commit()
    conn.close()

    try:
        resp = client.post(
            f'/api/configs/{config_id}/prompt',
            json={'url': 'https://login.example.com', 'selector': '#password'},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 204

        conn  = _open_db(tmp_env['db_path'])
        row   = conn.execute(
            "SELECT prompt FROM configurations WHERE id=?", (config_id,)
        ).fetchone()
        conn.close()
        data  = json.loads(row['prompt'])
        assert data['url']      == 'https://login.example.com'
        assert data['selector'] == '#password'
    finally:
        conn = _open_db(tmp_env['db_path'])
        conn.execute("DELETE FROM configurations WHERE id=?", (config_id,))
        conn.commit()
        conn.close()


def test_push_prompt_advances_status_to_valid(client, auth_token, tmp_env, seed_data):
    """Pushing prompt to an incomplete config with channel+header → status=valid."""
    conn = _open_db(tmp_env['db_path'])
    cur  = conn.execute(
        "INSERT INTO configurations "
        "  (owner_id, name, version, status, visibility) "
        "VALUES (?, 'prompt-valid', '-1', 'incomplete', 'private')",
        (seed_data['user_id'],),
    )
    config_id   = cur.lastrowid
    cur         = conn.execute(
        "INSERT INTO providers "
        "  (user_id, config_id, tag, extract_mode, nonce_start_marker) "
        "VALUES (?, ?, 'pv-ch', 'markers', 'OTP:')",
        (seed_data['user_id'], config_id),
    )
    conn.execute(
        "INSERT INTO provider_matchers (provider_id, sender_email) "
        "VALUES (?, 'pv@example.com')",
        (cur.lastrowid,),
    )
    conn.commit()
    conn.close()

    try:
        client.post(
            f'/api/configs/{config_id}/prompt',
            json={'url': 'https://example.com', 'selector': '#otp'},
            headers=_auth(auth_token),
        )
        configs = client.get('/api/configs', headers=_auth(auth_token)).get_json()
        found   = next((c for c in configs if c['id'] == config_id), None)
        assert found is not None
        assert found['status'] == 'valid'
    finally:
        conn = _open_db(tmp_env['db_path'])
        conn.execute("DELETE FROM configurations WHERE id=?", (config_id,))
        conn.commit()
        conn.close()


def test_push_prompt_wrong_owner_rejected(client, auth_token, tmp_env):
    """Non-owner cannot push a prompt to another user's config — returns 404."""
    conn = _open_db(tmp_env['db_path'])
    conn.execute("DELETE FROM users WHERE username='prompt-other'")
    cur  = conn.execute(
        "INSERT INTO users (username, password_hash) VALUES ('prompt-other', 'x')"
    )
    other_uid = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO configurations "
        "  (owner_id, name, version, status, visibility) "
        "VALUES (?, 'prompt-other-cfg', '-1', 'incomplete', 'private')",
        (other_uid,),
    )
    config_id = cur.lastrowid
    conn.commit()
    conn.close()

    try:
        resp = client.post(
            f'/api/configs/{config_id}/prompt',
            json={'url': 'https://example.com', 'selector': '#otp'},
            headers=_auth(auth_token),
        )
        assert resp.status_code == 404
    finally:
        conn = _open_db(tmp_env['db_path'])
        conn.execute("DELETE FROM users WHERE id=?", (other_uid,))
        conn.commit()
        conn.close()


def test_push_prompt_requires_auth(client, tmp_env, seed_data):
    conn = _open_db(tmp_env['db_path'])
    cur  = conn.execute(
        "INSERT INTO configurations "
        "  (owner_id, name, version, status, visibility) "
        "VALUES (?, 'prompt-noauth', '-1', 'incomplete', 'private')",
        (seed_data['user_id'],),
    )
    config_id = cur.lastrowid
    conn.commit()
    conn.close()

    try:
        resp = client.post(
            f'/api/configs/{config_id}/prompt',
            json={'url': 'https://example.com', 'selector': '#otp'},
        )
        assert resp.status_code == 401
    finally:
        conn = _open_db(tmp_env['db_path'])
        conn.execute("DELETE FROM configurations WHERE id=?", (config_id,))
        conn.commit()
        conn.close()


# ── Push — POST /api/configs/<id>/client-test ─────────────────────────────────

def test_report_client_test_increments_count(client, auth_token, valid_config, tmp_env):
    config_id = valid_config['config_id']

    conn   = _open_db(tmp_env['db_path'])
    before = conn.execute(
        "SELECT client_test_count FROM configurations WHERE id=?", (config_id,)
    ).fetchone()['client_test_count']
    conn.close()

    resp = client.post(f'/api/configs/{config_id}/client-test',
                       headers=_auth(auth_token))
    assert resp.status_code == 204

    conn  = _open_db(tmp_env['db_path'])
    after = conn.execute(
        "SELECT client_test_count FROM configurations WHERE id=?", (config_id,)
    ).fetchone()['client_test_count']
    conn.close()
    assert after == before + 1


def test_report_client_test_advances_to_valid_tested_at_threshold(
        client, auth_token, tmp_env, seed_data):
    """Third POST /client-test on a valid config advances status to valid_tested."""
    conn = _open_db(tmp_env['db_path'])
    cur  = conn.execute(
        "INSERT INTO configurations "
        "  (owner_id, name, version, status, visibility, client_test_count) "
        "VALUES (?, 'client-test-cfg', '-1', 'valid', 'private', 2)",
        (seed_data['user_id'],),
    )
    config_id = cur.lastrowid
    conn.commit()
    conn.close()

    try:
        resp = client.post(f'/api/configs/{config_id}/client-test',
                           headers=_auth(auth_token))
        assert resp.status_code == 204

        conn = _open_db(tmp_env['db_path'])
        row  = conn.execute(
            "SELECT status FROM configurations WHERE id=?", (config_id,)
        ).fetchone()
        conn.close()
        assert row['status'] == 'valid_tested'
    finally:
        conn = _open_db(tmp_env['db_path'])
        conn.execute("DELETE FROM configurations WHERE id=?", (config_id,))
        conn.commit()
        conn.close()


def test_report_client_test_requires_auth(client, valid_config):
    resp = client.post(f'/api/configs/{valid_config["config_id"]}/client-test')
    assert resp.status_code == 401

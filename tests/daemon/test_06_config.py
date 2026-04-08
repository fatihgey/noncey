"""
test_06_config — Server UI: configuration lifecycle.

Covers §8a (creation), §8b (publication), §8c (subscription),
§8d (subscription update), §8e (deletion / unsubscription).

Extension interactions (prompt push, test reporting) are emulated via the REST
API with an auth token; all other operations go through the UI session.
"""

import json
import re

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


# ── DB helpers ────────────────────────────────────────────────────────────────

def _mk_config(db_path, user_id, name, *, status='incomplete', visibility='private',
               description=None, prompt=None, version='-1'):
    conn = _open_db(db_path)
    cur  = conn.execute(
        "INSERT INTO configurations "
        "  (owner_id, name, version, status, visibility, description, prompt) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, name, version, status, visibility, description,
         json.dumps(prompt) if prompt else None),
    )
    config_id = cur.lastrowid
    conn.commit()
    conn.close()
    return config_id


def _mk_provider(db_path, user_id, config_id, tag='ch'):
    conn = _open_db(db_path)
    cur  = conn.execute(
        "INSERT INTO providers "
        "  (user_id, config_id, tag, extract_mode, nonce_start_marker) "
        "VALUES (?, ?, ?, 'markers', 'OTP:')",
        (user_id, config_id, tag),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return pid


def _mk_matcher(db_path, provider_id, sender='sender@example.com'):
    conn = _open_db(db_path)
    cur  = conn.execute(
        "INSERT INTO provider_matchers (provider_id, sender_email) VALUES (?, ?)",
        (provider_id, sender),
    )
    mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid


def _mk_valid_config(db_path, user_id, name):
    """Full valid config: channel + header + prompt, status=valid."""
    prompt    = {'url': 'https://example.com', 'url_match': 'prefix', 'selector': '#otp'}
    config_id = _mk_config(db_path, user_id, name, status='valid', prompt=prompt)
    pid       = _mk_provider(db_path, user_id, config_id, tag=name[:20] + '-ch')
    _mk_matcher(db_path, pid)
    return config_id, pid


def _mk_user(db_path, username):
    """Create a throwaway user; silently replaces any leftover from a prior failed run."""
    conn = _open_db(db_path)
    conn.execute("DELETE FROM users WHERE username=?", (username,))
    cur  = conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, 'x')", (username,)
    )
    uid = cur.lastrowid
    conn.commit()
    conn.close()
    return uid


def _del_config(db_path, config_id):
    conn = _open_db(db_path)
    conn.execute("DELETE FROM configurations WHERE id=?", (config_id,))
    conn.commit()
    conn.close()


def _del_user(db_path, uid):
    """Delete user and cascade to all their configurations and subscriptions."""
    conn = _open_db(db_path)
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()


def _get_config(db_path, config_id):
    conn = _open_db(db_path)
    row  = conn.execute(
        "SELECT * FROM configurations WHERE id=?", (config_id,)
    ).fetchone()
    conn.close()
    return row


# ── §8a — Creation Flow ───────────────────────────────────────────────────────

def test_create_config_success(logged_in_client, url, tmp_env, seed_data):
    resp = logged_in_client.post(url('admin.config_new'),
                                 data={'name': 'new-config'},
                                 follow_redirects=True)
    assert resp.status_code == 200

    conn = _open_db(tmp_env['db_path'])
    row  = conn.execute(
        "SELECT id, status, visibility FROM configurations "
        "WHERE owner_id=? AND name='new-config'",
        (seed_data['user_id'],),
    ).fetchone()
    conn.close()
    assert row is not None, 'config was not created'
    assert row['status']     == 'incomplete'
    assert row['visibility'] == 'private'

    _del_config(tmp_env['db_path'], row['id'])


def test_create_config_missing_name_rejected(logged_in_client, url):
    resp = logged_in_client.post(url('admin.config_new'),
                                 data={'name': ''},
                                 follow_redirects=True)
    assert resp.status_code == 200
    assert b'required' in resp.data.lower()


def test_edit_config_name(logged_in_client, url, tmp_env, seed_data):
    config_id = _mk_config(tmp_env['db_path'], seed_data['user_id'], 'edit-cfg-orig')
    try:
        resp = logged_in_client.post(
            url('admin.config_edit', config_id=config_id),
            data={'name': 'edit-cfg-renamed'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        row = _get_config(tmp_env['db_path'], config_id)
        assert row['name'] == 'edit-cfg-renamed'
    finally:
        _del_config(tmp_env['db_path'], config_id)


def test_create_channel_success(logged_in_client, url, tmp_env, seed_data):
    config_id = _mk_config(tmp_env['db_path'], seed_data['user_id'], 'ch-create-cfg')
    try:
        resp = logged_in_client.post(
            url('admin.channel_new', config_id=config_id),
            data={
                'tag':                'new-channel',
                'extract_mode':       'markers',
                'extract_source':     'body',
                'nonce_start_marker': 'OTP:',
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

        conn = _open_db(tmp_env['db_path'])
        row  = conn.execute(
            "SELECT id FROM providers WHERE config_id=? AND tag='new-channel'",
            (config_id,),
        ).fetchone()
        conn.close()
        assert row is not None, 'channel was not created'
    finally:
        _del_config(tmp_env['db_path'], config_id)


def test_create_channel_missing_tag_rejected(logged_in_client, url, tmp_env, seed_data):
    config_id = _mk_config(tmp_env['db_path'], seed_data['user_id'], 'ch-notag-cfg')
    try:
        resp = logged_in_client.post(
            url('admin.channel_new', config_id=config_id),
            data={
                'tag':                '',
                'extract_mode':       'markers',
                'nonce_start_marker': 'OTP:',
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'required' in resp.data.lower()
    finally:
        _del_config(tmp_env['db_path'], config_id)


def test_edit_channel_extraction_settings(logged_in_client, url, tmp_env, seed_data):
    config_id = _mk_config(tmp_env['db_path'], seed_data['user_id'], 'ch-edit-cfg')
    pid       = _mk_provider(tmp_env['db_path'], seed_data['user_id'], config_id, tag='orig-ch')
    try:
        resp = logged_in_client.post(
            url('admin.channel_edit', config_id=config_id, provider_id=pid),
            data={
                'tag':                'orig-ch',
                'extract_mode':       'markers',
                'extract_source':     'body',
                'nonce_start_marker': 'NEWMARKER:',
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

        conn = _open_db(tmp_env['db_path'])
        row  = conn.execute(
            "SELECT nonce_start_marker FROM providers WHERE id=?", (pid,)
        ).fetchone()
        conn.close()
        assert row['nonce_start_marker'] == 'NEWMARKER:'
    finally:
        _del_config(tmp_env['db_path'], config_id)


def test_delete_channel(logged_in_client, url, tmp_env, seed_data):
    # Give the config a prompt so it won't be auto-deleted when the channel is removed.
    config_id, pid = _mk_valid_config(tmp_env['db_path'], seed_data['user_id'], 'ch-del-cfg')
    try:
        resp = logged_in_client.post(
            url('admin.channel_delete', config_id=config_id, provider_id=pid),
            follow_redirects=True,
        )
        assert resp.status_code == 200

        conn = _open_db(tmp_env['db_path'])
        row  = conn.execute("SELECT id FROM providers WHERE id=?", (pid,)).fetchone()
        conn.close()
        assert row is None, 'channel was not deleted'
    finally:
        _del_config(tmp_env['db_path'], config_id)


def test_add_header_success(logged_in_client, url, tmp_env, seed_data):
    config_id = _mk_config(tmp_env['db_path'], seed_data['user_id'], 'hdr-add-cfg')
    pid       = _mk_provider(tmp_env['db_path'], seed_data['user_id'], config_id)
    try:
        resp = logged_in_client.post(
            url('admin.matcher_new', config_id=config_id, provider_id=pid),
            data={
                'sender_mode':   'custom',
                'sender_custom': 'otp@example.com',
                'subject_mode':  'any',
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

        conn = _open_db(tmp_env['db_path'])
        row  = conn.execute(
            "SELECT id FROM provider_matchers "
            "WHERE provider_id=? AND sender_email='otp@example.com'",
            (pid,),
        ).fetchone()
        conn.close()
        assert row is not None, 'header/matcher was not created'
    finally:
        _del_config(tmp_env['db_path'], config_id)


def test_add_header_both_empty_rejected(logged_in_client, url, tmp_env, seed_data):
    config_id = _mk_config(tmp_env['db_path'], seed_data['user_id'], 'hdr-empty-cfg')
    pid       = _mk_provider(tmp_env['db_path'], seed_data['user_id'], config_id)
    try:
        resp = logged_in_client.post(
            url('admin.matcher_new', config_id=config_id, provider_id=pid),
            data={'sender_mode': 'any', 'subject_mode': 'any'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'At least one' in resp.data
    finally:
        _del_config(tmp_env['db_path'], config_id)


def test_delete_header(logged_in_client, url, tmp_env, seed_data):
    config_id = _mk_config(tmp_env['db_path'], seed_data['user_id'], 'hdr-del-cfg')
    pid       = _mk_provider(tmp_env['db_path'], seed_data['user_id'], config_id)
    mid       = _mk_matcher(tmp_env['db_path'], pid)
    try:
        resp = logged_in_client.post(
            url('admin.matcher_delete',
                config_id=config_id, provider_id=pid, matcher_id=mid),
            follow_redirects=True,
        )
        assert resp.status_code == 200

        conn = _open_db(tmp_env['db_path'])
        row  = conn.execute(
            "SELECT id FROM provider_matchers WHERE id=?", (mid,)
        ).fetchone()
        conn.close()
        assert row is None, 'header/matcher was not deleted'
    finally:
        _del_config(tmp_env['db_path'], config_id)


def test_config_status_becomes_valid_when_complete(
        logged_in_client, auth_token, url, tmp_env, seed_data):
    """Pushing a prompt to a config with channel+header transitions status to valid."""
    config_id = _mk_config(tmp_env['db_path'], seed_data['user_id'], 'status-valid-cfg')
    pid       = _mk_provider(tmp_env['db_path'], seed_data['user_id'], config_id)
    _mk_matcher(tmp_env['db_path'], pid)
    try:
        resp = logged_in_client.post(
            f'/api/configs/{config_id}/prompt',
            json={'url': 'https://example.com', 'selector': '#otp'},
            headers={'Authorization': f'Bearer {auth_token}'},
        )
        assert resp.status_code == 204

        row = _get_config(tmp_env['db_path'], config_id)
        assert row['status'] == 'valid'
    finally:
        _del_config(tmp_env['db_path'], config_id)


def test_config_status_reverts_to_incomplete_when_channel_removed(
        logged_in_client, url, tmp_env, seed_data):
    """Removing the only channel from a valid config reverts status to incomplete."""
    config_id, pid = _mk_valid_config(
        tmp_env['db_path'], seed_data['user_id'], 'revert-cfg')
    try:
        logged_in_client.post(
            url('admin.channel_delete', config_id=config_id, provider_id=pid),
            follow_redirects=True,
        )
        row = _get_config(tmp_env['db_path'], config_id)
        assert row is not None, 'config should not be auto-deleted (it has a prompt)'
        assert row['status'] == 'incomplete'
    finally:
        _del_config(tmp_env['db_path'], config_id)


def test_auto_delete_config_when_empty(logged_in_client, url, tmp_env, seed_data):
    """Config with no remaining channels and no prompt is auto-deleted."""
    config_id = _mk_config(tmp_env['db_path'], seed_data['user_id'], 'auto-del-cfg')
    pid       = _mk_provider(tmp_env['db_path'], seed_data['user_id'], config_id)
    try:
        resp = logged_in_client.post(
            url('admin.channel_delete', config_id=config_id, provider_id=pid),
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert _get_config(tmp_env['db_path'], config_id) is None, \
            'config should have been auto-deleted'
    finally:
        _del_config(tmp_env['db_path'], config_id)   # no-op if already gone


def test_activate_config(logged_in_client, url, tmp_env, seed_data):
    config_id, _ = _mk_valid_config(
        tmp_env['db_path'], seed_data['user_id'], 'activate-cfg')
    try:
        logged_in_client.post(
            url('admin.config_activate', config_id=config_id),
            follow_redirects=True,
        )
        assert _get_config(tmp_env['db_path'], config_id)['activated'] == 1
    finally:
        _del_config(tmp_env['db_path'], config_id)


def test_deactivate_config(logged_in_client, url, tmp_env, seed_data):
    config_id, _ = _mk_valid_config(
        tmp_env['db_path'], seed_data['user_id'], 'deactivate-cfg')
    conn = _open_db(tmp_env['db_path'])
    conn.execute("UPDATE configurations SET activated=1 WHERE id=?", (config_id,))
    conn.commit()
    conn.close()
    try:
        logged_in_client.post(
            url('admin.config_activate', config_id=config_id),
            follow_redirects=True,
        )
        assert _get_config(tmp_env['db_path'], config_id)['activated'] == 0
    finally:
        _del_config(tmp_env['db_path'], config_id)


# ── §8b — Publication Flow ────────────────────────────────────────────────────

def test_submit_config_for_review(logged_in_client, url, tmp_env, seed_data):
    config_id = _mk_config(tmp_env['db_path'], seed_data['user_id'], 'submit-cfg',
                           status='valid_tested', description='A description')
    try:
        resp = logged_in_client.post(
            url('admin.config_submit', config_id=config_id),
            data={'tos_accepted': '1'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert _get_config(tmp_env['db_path'], config_id)['status'] == 'pending_review'
    finally:
        _del_config(tmp_env['db_path'], config_id)


def test_submit_requires_valid_tested_status(logged_in_client, url, tmp_env, seed_data):
    config_id, _ = _mk_valid_config(
        tmp_env['db_path'], seed_data['user_id'], 'submit-not-tested')
    try:
        resp = logged_in_client.post(
            url('admin.config_submit', config_id=config_id),
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'tested' in resp.data.lower()
        assert _get_config(tmp_env['db_path'], config_id)['status'] == 'valid'
    finally:
        _del_config(tmp_env['db_path'], config_id)


def test_admin_approve_config(admin_client, url, tmp_env, seed_data):
    config_id = _mk_config(tmp_env['db_path'], seed_data['user_id'], 'approve-cfg',
                           status='pending_review', description='For approval')
    try:
        resp = admin_client.post(
            url('admin.admin_marketplace_approve', config_id=config_id),
            follow_redirects=True,
        )
        assert resp.status_code == 200
        row = _get_config(tmp_env['db_path'], config_id)
        assert row['visibility'] == 'public'
        assert row['status']     == 'valid'
        assert re.match(r'^\d{6}-\d{2}$', row['version'])
    finally:
        _del_config(tmp_env['db_path'], config_id)


def test_admin_reject_config(admin_client, url, tmp_env, seed_data):
    config_id = _mk_config(tmp_env['db_path'], seed_data['user_id'], 'reject-cfg',
                           status='pending_review')
    try:
        resp = admin_client.post(
            url('admin.admin_marketplace_reject', config_id=config_id),
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert _get_config(tmp_env['db_path'], config_id)['status'] == 'valid_tested'
    finally:
        _del_config(tmp_env['db_path'], config_id)


# ── §8c — Subscription Flow ───────────────────────────────────────────────────

def test_subscribe_to_public_config(logged_in_client, url, tmp_env, seed_data):
    other_uid = _mk_user(tmp_env['db_path'], 'sub-owner')
    config_id = _mk_config(tmp_env['db_path'], other_uid, 'public-sub-cfg',
                           status='valid', visibility='public', version='202401-01')
    try:
        resp = logged_in_client.post(
            url('admin.marketplace_subscribe', src_config_id=config_id),
            follow_redirects=True,
        )
        assert resp.status_code == 200

        conn = _open_db(tmp_env['db_path'])
        sub  = conn.execute(
            "SELECT id FROM subscriptions WHERE user_id=? AND config_id=?",
            (seed_data['user_id'], config_id),
        ).fetchone()
        conn.close()
        assert sub is not None, 'subscription was not created'
    finally:
        _del_user(tmp_env['db_path'], other_uid)   # cascades to config + subscription


def test_subscribe_already_subscribed_rejected(logged_in_client, url, tmp_env, seed_data):
    other_uid = _mk_user(tmp_env['db_path'], 'dup-sub-owner')
    config_id = _mk_config(tmp_env['db_path'], other_uid, 'dup-sub-cfg',
                           status='valid', visibility='public', version='202401-01')
    conn = _open_db(tmp_env['db_path'])
    conn.execute("INSERT INTO subscriptions (user_id, config_id) VALUES (?, ?)",
                 (seed_data['user_id'], config_id))
    conn.commit()
    conn.close()
    try:
        resp = logged_in_client.post(
            url('admin.marketplace_subscribe', src_config_id=config_id),
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b'Already subscribed' in resp.data
    finally:
        _del_user(tmp_env['db_path'], other_uid)


# ── §8d — Subscription Update Flow ───────────────────────────────────────────

def test_update_subscription_to_newer_version(logged_in_client, url, tmp_env, seed_data):
    other_uid = _mk_user(tmp_env['db_path'], 'upd-owner')
    v1_id     = _mk_config(tmp_env['db_path'], other_uid, 'upd-sub-cfg',
                           status='valid', visibility='public', version='202401-01')
    v2_id     = _mk_config(tmp_env['db_path'], other_uid, 'upd-sub-cfg',
                           status='valid', visibility='public', version='202402-01')
    conn = _open_db(tmp_env['db_path'])
    conn.execute("INSERT INTO subscriptions (user_id, config_id) VALUES (?, ?)",
                 (seed_data['user_id'], v1_id))
    conn.commit()
    conn.close()
    try:
        resp = logged_in_client.post(
            url('admin.marketplace_update', old_config_id=v1_id, new_config_id=v2_id),
            follow_redirects=True,
        )
        assert resp.status_code == 200

        conn = _open_db(tmp_env['db_path'])
        sub  = conn.execute(
            "SELECT config_id FROM subscriptions WHERE user_id=? AND config_id=?",
            (seed_data['user_id'], v2_id),
        ).fetchone()
        conn.close()
        assert sub is not None, 'subscription was not updated to v2'
    finally:
        _del_user(tmp_env['db_path'], other_uid)


# ── §8e — Unsubscription / Deletion ──────────────────────────────────────────

def test_unsubscribe_removes_subscription(logged_in_client, url, tmp_env, seed_data):
    other_uid = _mk_user(tmp_env['db_path'], 'unsub-owner')
    config_id = _mk_config(tmp_env['db_path'], other_uid, 'unsub-cfg',
                           status='valid', visibility='public', version='202401-01')
    conn = _open_db(tmp_env['db_path'])
    conn.execute("INSERT INTO subscriptions (user_id, config_id) VALUES (?, ?)",
                 (seed_data['user_id'], config_id))
    conn.commit()
    conn.close()
    try:
        resp = logged_in_client.post(
            url('admin.marketplace_unsubscribe', config_id=config_id),
            follow_redirects=True,
        )
        assert resp.status_code == 200

        conn = _open_db(tmp_env['db_path'])
        sub  = conn.execute(
            "SELECT id FROM subscriptions WHERE user_id=? AND config_id=?",
            (seed_data['user_id'], config_id),
        ).fetchone()
        conn.close()
        assert sub is None, 'subscription was not removed'
    finally:
        _del_user(tmp_env['db_path'], other_uid)


def test_delete_private_config(logged_in_client, url, tmp_env, seed_data):
    config_id = _mk_config(tmp_env['db_path'], seed_data['user_id'], 'del-priv-cfg')
    resp = logged_in_client.post(
        url('admin.config_delete', config_id=config_id),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _get_config(tmp_env['db_path'], config_id) is None


def test_delete_config_requires_ownership(logged_in_client, url, tmp_env):
    """Non-owner attempting to delete another user's private config is rejected."""
    other_uid = _mk_user(tmp_env['db_path'], 'del-owner')
    config_id = _mk_config(tmp_env['db_path'], other_uid, 'other-del-cfg')
    try:
        logged_in_client.post(
            url('admin.config_delete', config_id=config_id),
            follow_redirects=True,
        )
        assert _get_config(tmp_env['db_path'], config_id) is not None, \
            'config should not be deleted by non-owner'
    finally:
        _del_user(tmp_env['db_path'], other_uid)

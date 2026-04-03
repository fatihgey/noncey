# Noncey — Test Suite Overview

## Running the Tests

```bash
cd tests
pip install -r requirements.txt

# Quick smoke (ingest + auth + nonces, no external deps):
./run_smoke.sh

# All daemon tests including Server UI:
./run_smoke.sh --all

# Include live Postfix delivery test:
NONCEY_TEST_MAIL=1 ./run_smoke.sh --all

# Include Chrome extension auto-fill test (requires: playwright install chromium):
NONCEY_TEST_EXTENSION=1 ./run_smoke.sh --all
```

The smoke tests are safe to run against a production installation — they use the isolated `_test_` identity and clean up all data on exit.

---

## Structure

```
tests/
├── conftest.py                     # Shared fixtures (DB, Flask app, auth token, seeded nonce)
├── pytest.ini
├── requirements.txt
├── run_smoke.sh
├── fixtures/
│   └── sample_otp.eml              # Sample email for ingest tests
├── daemon/
│   ├── test_01_ingest.py           # Nonce extraction via ingest pipe
│   ├── test_02_api_auth.py         # REST auth endpoints
│   ├── test_03_api_nonces.py       # REST nonce endpoints
│   ├── test_04_admin.py            # Server UI: access, auth, user management
│   ├── test_05_mail.py             # E2E: real Postfix delivery (opt-in)
│   ├── test_06_config.py           # Server UI: configuration lifecycle (new)
│   └── test_07_api_configs.py      # REST API: config sync — pull + push (new)
└── client.chromeextension/
    ├── test_10_autofill.py         # E2E: extension autofill (opt-in)
    ├── testserver.py               # Static HTTP server for test page
    └── testpage/index.html         # Test page with OTP input field
```

---

## 1. Daemon

Tests in this section use the Flask test client or invoke `ingest.py` as a subprocess. No real network or browser is required.

### 1.1 Server UI Access and User Management

**File:** `daemon/test_04_admin.py`

Tests the Server UI Blueprint served at `/auth/`. Authentication is a Flask signed cookie session managed entirely by Flask — no Apache BasicAuth. The test client must log in via `POST /auth/login` to obtain a session before accessing protected routes.

#### Server UI Authentication

| Test | What it verifies |
|------|-----------------|
| `test_login_returns_session` | `POST /auth/login` with valid credentials → 302 redirect to dashboard; session cookie set |
| `test_login_wrong_password_rejected` | Invalid password → login page re-rendered with error message |
| `test_login_unknown_user_rejected` | Non-existent username → login page with error message |
| `test_dashboard_requires_auth` | `GET /auth/` without session → redirect to `/auth/login` |
| `test_logout_clears_session` | `POST /auth/logout` → session cleared; subsequent `GET /auth/` redirects to login |

#### Dashboard

| Test | What it verifies |
|------|-----------------|
| `test_dashboard_ok` | `GET /auth/` with valid session returns 200 |
| `test_dashboard_lists_test_user` | Dashboard HTML contains the seeded test username |

#### User Management (Admin)

| Test | What it verifies |
|------|-----------------|
| `test_create_user_success` | Valid `POST /auth/admin/users/new` creates user and redirects to list |
| `test_create_user_password_mismatch` | Mismatched passwords → "do not match" error |
| `test_create_user_empty_password` | Empty password → "empty" / "required" error |
| `test_create_duplicate_user` | Duplicate username → "already exists" error |
| `test_edit_user` | `POST /auth/admin/users/<id>/edit` with updated email / is_admin → changes persisted in DB |
| `test_delete_user` | `POST /auth/admin/users/<id>/delete` removes user; page shows "deleted" |

#### Account (Self-service)

| Test | What it verifies |
|------|-----------------|
| `test_change_password_success` | `POST /auth/account/password` with valid current + new password → updated; re-login with new password succeeds |
| `test_change_password_wrong_current_rejected` | Wrong current password → error message; password unchanged |

---

### 1.2 Configuration

**File:** `daemon/test_06_config.py` *(new)*

Tests the full Provider Configuration lifecycle via the Server UI (`/auth/`). The Chrome extension's interactions (prompt push, test reporting) are emulated directly via REST API calls in the same test session. Sub-sections follow the lifecycle flows defined in `CONCEPT_CONFIGURATION.md §8`.

#### §8a — Creation Flow

Covers creating a configuration, building it out with Channels and Headers, pushing the fill Prompt (as the extension would), and activating.

| Test | What it verifies |
|------|-----------------|
| `test_create_config_success` | `POST /auth/configs/new` with name → config created at `status=incomplete, visibility=private` |
| `test_create_config_missing_name_rejected` | Empty name → "required" error |
| `test_edit_config_name` | `POST /auth/configs/<id>/edit` with updated name/description → changes persisted in DB |
| `test_create_channel_success` | `POST /auth/configs/<id>/channels/new` → channel created; appears in response |
| `test_create_channel_missing_tag_rejected` | Empty channel tag → "required" error |
| `test_edit_channel_extraction_settings` | `POST /auth/configs/<id>/channels/<pid>/edit` with new `extract_mode` / markers → persisted in DB |
| `test_delete_channel` | `POST /auth/configs/<id>/channels/<pid>/delete` removes channel from DB |
| `test_add_header_success` | `POST /auth/configs/<id>/channels/<pid>/headers/new` → header created; sender email appears in response |
| `test_add_header_both_empty_rejected` | Both `sender_email` and `subject_pattern` empty → "At least one" error |
| `test_delete_header` | `POST /auth/configs/<id>/channels/<pid>/headers/<mid>/delete` removes header from DB |
| `test_config_status_becomes_valid_when_complete` | Config with channel+header+prompt transitions automatically to `status=valid` |
| `test_config_status_reverts_to_incomplete_when_channel_removed` | Removing the only channel from a `valid` config → `status=incomplete` |
| `test_auto_delete_config_when_empty` | Config with no channels and no prompt is automatically deleted |
| `test_activate_config` | `POST /auth/configs/<id>/activate` on a valid config → `activated=1` |
| `test_deactivate_config` | `POST /auth/configs/<id>/activate` (toggle) on active config → `activated=0` |

#### §8b — Publication Flow

| Test | What it verifies |
|------|-----------------|
| `test_submit_config_for_review` | `POST /auth/configs/<id>/submit` on `valid_tested` config → `status=pending_review` |
| `test_submit_requires_valid_tested_status` | Submitting a config at `status=valid` (not yet tested) → rejected with error |
| `test_admin_approve_config` | `POST /auth/admin/marketplace/<id>/approve` → `visibility=public`, version assigned as `YYYYMM-NN` |
| `test_admin_reject_config` | `POST /auth/admin/marketplace/<id>/reject` → status returned to `valid_tested`; owner may revise and resubmit |

#### §8c — Subscription Flow

| Test | What it verifies |
|------|-----------------|
| `test_subscribe_to_public_config` | `POST /auth/marketplace/<id>/subscribe` → row created in `subscriptions`; config appears on dashboard |
| `test_subscribe_already_subscribed_rejected` | Duplicate subscription → error or 409 |

#### §8d — Subscription Update Flow

| Test | What it verifies |
|------|-----------------|
| `test_update_subscription_to_newer_version` | `POST /auth/marketplace/<id>/update/<local_id>` → `subscriptions` row updated to reference new `config_id` |

#### §8e — Deactivation / Unsubscription / Deletion

| Test | What it verifies |
|------|-----------------|
| `test_unsubscribe_removes_subscription` | POST to unsubscribe on a subscribed public config → `subscriptions` row deleted; config absent from dashboard |
| `test_delete_private_config` | `POST /auth/configs/<id>/delete` → config, channels, headers, and prompt all removed |
| `test_delete_config_requires_ownership` | Non-owner attempting to delete another user's config → 403 or 404 |

---

### 1.3 Extracting Nonce from Input

**File:** `daemon/test_01_ingest.py` (5 tests)

Tests the `ingest.py` pipe that Postfix calls for incoming OTP emails. Each test invokes the script as a subprocess, feeds a synthetic `.eml` on stdin, and inspects SQLite directly.

| Test | What it verifies |
|------|-----------------|
| `test_ingest_writes_nonce_to_db` | ingest.py extracts nonce from email body and inserts a row into `nonces` |
| `test_ingest_archives_eml` | ingest.py writes the raw `.eml` file to the archive directory |
| `test_ingest_unknown_user_exits_67` | Unknown recipient → exits with `EX_NOUSER` (67) |
| `test_ingest_unmatched_sender_exits_0` | Unrecognised sender → exits 0, archives email, no nonce inserted |
| `test_ingest_bad_recipient_format_exits_67` | Recipient local part without `nonce-` prefix → exits 67 |

---

### 1.4 Serving Nonce to Client

**Files:** `daemon/test_02_api_auth.py` (9 tests), `daemon/test_03_api_nonces.py` (8 tests)

Tests the REST API used by the Chrome extension. All tests use the Flask test client with JWT Bearer auth.

#### Authentication (`test_02_api_auth.py`)

| Test | What it verifies |
|------|-----------------|
| `test_login_returns_token` | `POST /api/auth/login` returns 200 with `token` and `expires_at` |
| `test_login_wrong_password_rejected` | Invalid password → 401 |
| `test_login_unknown_user_rejected` | Non-existent user → 401 |
| `test_login_missing_fields_rejected` | Empty JSON body → 400 |
| `test_nonces_endpoint_requires_auth` | `GET /api/nonces` without `Authorization` header → 401 |
| `test_invalid_bearer_token_rejected` | Malformed JWT → 401 |
| `test_logout_returns_204` | `POST /api/auth/logout` with valid token → 204 |
| `test_logout_invalidates_token` | Token is unusable immediately after logout |
| `test_logout_requires_auth` | `POST /api/auth/logout` without auth → 401 |

#### Nonce Retrieval & Deletion (`test_03_api_nonces.py`)

| Test | What it verifies |
|------|-----------------|
| `test_get_nonces_returns_list` | `GET /api/nonces` returns 200 with list payload |
| `test_get_nonces_includes_seeded_nonce` | Seeded nonce appears with correct `id`, `nonce_value`, `provider_tag`, `configuration_name`, `age_seconds`, `expires_at` |
| `test_get_nonces_requires_auth` | `GET /api/nonces` without auth → 401 |
| `test_get_nonces_only_returns_own_data` | All returned nonces have required fields (user-isolation spot-check) |
| `test_delete_nonce_returns_204` | `DELETE /api/nonces/<id>` → 204 |
| `test_deleted_nonce_absent_from_list` | Deleted nonce no longer appears in `GET /api/nonces` |
| `test_delete_nonexistent_nonce_returns_404` | `DELETE /api/nonces/999999` → 404 |
| `test_delete_nonce_requires_auth` | `DELETE /api/nonces/<id>` without auth → 401 |

---

### 1.5 Sync with Client

**File:** `daemon/test_07_api_configs.py` *(new)*

Tests the REST API endpoints the Chrome extension uses to synchronise configuration data with the daemon: pulling the config list and pushing field data. All tests use the Flask test client with JWT Bearer auth, emulating the extension without a real browser.

#### Pull — Fetching Configurations (`GET /api/configs`)

| Test | What it verifies |
|------|-----------------|
| `test_get_configs_returns_list` | `GET /api/configs` returns 200 with list payload |
| `test_get_configs_includes_own_valid_config` | Own valid config appears with `id`, `name`, `status`, `activated`, `prompt`, `provider_tags` |
| `test_get_configs_includes_subscribed_public_config` | Subscribed public config appears with `is_owned=false` and read-only prompt |
| `test_get_configs_excludes_incomplete_configs` | Configs at `status=incomplete` are not returned |
| `test_get_configs_only_returns_own_and_subscribed` | No other users' private configs appear |
| `test_get_configs_requires_auth` | `GET /api/configs` without `Authorization` → 401 |

#### Push — Storing Fill Prompt (`POST /api/configs/<id>/prompt`)

| Test | What it verifies |
|------|-----------------|
| `test_push_prompt_stores_url_and_selector` | `POST /api/configs/<id>/prompt` with `{url, selector}` → 200; prompt persisted to DB |
| `test_push_prompt_advances_status_to_valid` | Pushing prompt to a config that already has channel+header → `status=valid` reflected in subsequent `GET /api/configs` |
| `test_push_prompt_wrong_owner_rejected` | Non-owner pushing prompt to another user's config → 403 or 404 |
| `test_push_prompt_requires_auth` | `POST /api/configs/<id>/prompt` without auth → 401 |

#### Push — Reporting Successful Fills (`POST /api/configs/<id>/client-test`)

| Test | What it verifies |
|------|-----------------|
| `test_report_client_test_increments_count` | `POST /api/configs/<id>/client-test` → 204; `client_test_count` incremented in DB |
| `test_report_client_test_advances_to_valid_tested_at_threshold` | Third `POST /api/configs/<id>/client-test` → `status` transitions to `valid_tested` |
| `test_report_client_test_requires_auth` | `POST /api/configs/<id>/client-test` without auth → 401 |

---

### 1.6 Self Maintenance (Lifecycle / Cleanup)

N/A — no automated tests.

---

## 2. Client (Chrome Extension)

No standalone client-only tests. The only extension test (autofill) requires a running daemon instance and is listed under E2E below.

---

## 3. E2E (Daemon + Client)

These tests exercise real subsystems end-to-end. Both are **opt-in** and skipped unless the corresponding environment variable is set.

### 3.1 Full Email Delivery Pipeline

**File:** `daemon/test_05_mail.py` (1 test)
**Requires:** Running Postfix with noncey transport installed; `NONCEY_TEST_MAIL=1`

| Test | What it verifies |
|------|-----------------|
| `test_mail_delivery_end_to_end` | Sends a real SMTP message → Postfix → nonce-pipe → `ingest.py` → SQLite; nonce must appear in DB within 15 s |

Optional env overrides: `NONCEY_TEST_SMTP_HOST` (default: `localhost`), `NONCEY_TEST_SMTP_PORT` (default: `25`).

### 3.2 Chrome Extension Autofill

**File:** `client.chromeextension/test_10_autofill.py` (1 test)
**Requires:** Playwright + Chromium (`playwright install chromium`); `NONCEY_TEST_EXTENSION=1`

The fixture chain:
1. Starts a static HTTP server serving `testpage/index.html` (contains `#otp-field`)
2. Runs Flask daemon on a real TCP port (15000) so the extension service worker can reach it
3. Loads the unpacked extension into headless Chromium
4. Injects server URL, API token, and provider into `chrome.storage.sync`
5. Seeds a nonce directly into the DB

| Test | What it verifies |
|------|-----------------|
| `test_extension_autofills_otp_field` | Extension detects test page URL, polls `/api/nonces`, fills `#otp-field` with the seeded nonce value within 10 s; nonce is deleted from DB after fill |

---

## Coverage Summary

| Component | Group | Tests | File(s) |
|-----------|-------|------:|---------|
| Daemon | Server UI access & user management | ~15 | test_04_admin.py |
| Daemon | Configuration lifecycle | ~22 | test_06_config.py *(new)* |
| Daemon | Extracting nonce from input | 5 | test_01_ingest.py |
| Daemon | Serving nonce to client | 17 | test_02_api_auth.py, test_03_api_nonces.py |
| Daemon | Sync with client | ~13 | test_07_api_configs.py *(new)* |
| Daemon | Self maintenance | — | N/A |
| Client | — | — | no standalone tests |
| E2E | Full mail delivery | 1 | test_05_mail.py |
| E2E | Extension autofill | 1 | test_10_autofill.py |
| **Total** | | **~74** | |

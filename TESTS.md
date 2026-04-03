# Noncey — Test Suite Overview

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
│   ├── test_04_admin.py            # Admin UI CRUD
│   └── test_05_mail.py             # E2E: real Postfix delivery (opt-in)
└── client.chromeextension/
    ├── test_10_autofill.py         # E2E: extension autofill (opt-in)
    ├── testserver.py               # Static HTTP server for test page
    └── testpage/index.html         # Test page with OTP input field
```

---

## 1. Daemon

Tests in this section use the Flask test client or invoke `ingest.py` as a subprocess. No real network or browser is required.

### 1.1 Configuration Management

**File:** `daemon/test_04_admin.py` (14 tests)

Tests the Admin Blueprint (served at `/noncey/`) for all CRUD operations. Auth is handled by Apache in production; the blueprint itself has no auth layer, so the test client hits routes directly.

| Test | What it verifies |
|------|-----------------|
| `test_dashboard_ok` | `GET /noncey/` returns 200 |
| `test_dashboard_trailing_slash_redirect` | `GET /noncey` (no slash) returns 200 or redirect |
| `test_dashboard_lists_test_user` | Dashboard HTML contains the seeded test username |
| `test_create_user_success` | Valid POST to `/noncey/users/new` creates user and redirects to list |
| `test_create_user_password_mismatch` | Mismatched passwords rejected with "do not match" message |
| `test_create_user_empty_password` | Empty password rejected with "empty" / "required" message |
| `test_create_duplicate_user` | Duplicate username rejected with "already exists" message |
| `test_delete_user` | POST to `/noncey/users/<id>/delete` removes user; page shows "deleted" |
| `test_create_provider` | POST to `/noncey/users/<id>/providers/new` creates provider; appears in response |
| `test_create_provider_missing_tag_rejected` | Empty provider tag rejected with "required" message |
| `test_delete_provider` | POST to `/noncey/users/<id>/providers/<id>/delete` removes provider from DB |
| `test_add_matcher` | POST to matchers/new creates matcher; sender email appears in response |
| `test_add_matcher_both_empty_rejected` | Both `sender_email` and `subject_pattern` empty → "At least one" error |
| `test_delete_matcher` | POST to matchers/<id>/delete removes matcher from DB |

### 1.2 Extracting Nonce from Input

**File:** `daemon/test_01_ingest.py` (5 tests)

Tests the `ingest.py` pipe that Postfix calls for incoming OTP emails. Each test invokes the script as a subprocess, feeds a synthetic `.eml` on stdin, and inspects SQLite directly.

| Test | What it verifies |
|------|-----------------|
| `test_ingest_writes_nonce_to_db` | ingest.py extracts nonce from email body and inserts a row into `nonces` |
| `test_ingest_archives_eml` | ingest.py writes the raw `.eml` file to the archive directory |
| `test_ingest_unknown_user_exits_67` | Unknown recipient → exits with `EX_NOUSER` (67) |
| `test_ingest_unmatched_sender_exits_0` | Unrecognised sender → exits 0, archives email, no nonce inserted |
| `test_ingest_bad_recipient_format_exits_67` | Recipient local part without `nonce-` prefix → exits 67 |

### 1.3 Serving Nonce to Client

**Files:** `daemon/test_02_api_auth.py` (9 tests), `daemon/test_03_api_nonces.py` (8 tests)

Tests the REST API used by the Chrome extension. All tests use the Flask test client.

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
| `test_get_nonces_includes_seeded_nonce` | Seeded nonce appears with correct `id`, `value`, `provider_tag`, `age_seconds`, `expires_at` |
| `test_get_nonces_requires_auth` | `GET /api/nonces` without auth → 401 |
| `test_get_nonces_only_returns_own_data` | All returned nonces have required fields (user-isolation spot-check) |
| `test_delete_nonce_returns_204` | `DELETE /api/nonces/<id>` → 204 |
| `test_deleted_nonce_absent_from_list` | Deleted nonce no longer appears in `GET /api/nonces` |
| `test_delete_nonexistent_nonce_returns_404` | `DELETE /api/nonces/999999` → 404 |
| `test_delete_nonce_requires_auth` | `DELETE /api/nonces/<id>` without auth → 401 |

### 1.4 Sync with Client

Not covered by automated tests.

### 1.5 Self Maintenance (Lifecycle / Cleanup)

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
| Daemon | Configuration management | 14 | test_04_admin.py |
| Daemon | Extracting nonce from input | 5 | test_01_ingest.py |
| Daemon | Serving nonce to client | 17 | test_02_api_auth.py, test_03_api_nonces.py |
| Daemon | Sync with client | — | not covered |
| Daemon | Self maintenance | — | N/A |
| Client | — | — | no standalone tests |
| E2E | Full mail delivery | 1 | test_05_mail.py |
| E2E | Extension autofill | 1 | test_10_autofill.py |
| **Total** | | **38** | |

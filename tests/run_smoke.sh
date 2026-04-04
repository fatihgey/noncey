#!/usr/bin/env bash
# noncey smoke test runner
#
# Default (no flags): runs ingest + auth + nonces tests only.
#   No external dependencies.  Safe to run against production.
#   Uses the isolated _test_ identity; all data is cleaned up on exit.
#
# Usage:
#   ./run_smoke.sh                         # quick smoke (tests 01-03)
#   ./run_smoke.sh --all                   # all tests (skips mail + extension unless flags set)
#   NONCEY_TEST_MAIL=1 ./run_smoke.sh --all        # include live mail test
#   NONCEY_TEST_EXTENSION=1 ./run_smoke.sh --all   # include extension test
#
# Exit code mirrors pytest: 0 = all passed, non-zero = failure or error.

set -euo pipefail
cd "$(dirname "$0")"

pip install -q -r requirements.txt
pip install -q -r ../../noncey.daemon/requirements.txt

PYTEST_ARGS=(-v --tb=short)
TESTS=(
    daemon/test_01_ingest.py
    daemon/test_02_api_auth.py
    daemon/test_03_api_nonces.py
)

if [[ "${1-}" == '--all' ]]; then
    TESTS+=(
        daemon/test_04_admin.py
        daemon/test_05_mail.py
        "client.chromeextension/test_10_autofill.py"
    )
    shift
fi

exec pytest "${PYTEST_ARGS[@]}" "${TESTS[@]}" "$@"

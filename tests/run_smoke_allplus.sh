#playwright install chromium
#playwright install-deps chromium
NONCEY_TEST_EXTENSION=1 NONCEY_TEST_MAIL=1 NONCEY_TEST_MAIL_CONF=/opt/noncey/daemon/etc/noncey.conf ./run_smoke.sh --all

# noncey

Email OTP relay — automatically intercepts OTP emails, extracts the code, and fills
it into the browser (or forwards it from your phone).

```
incoming email
      │
      ▼
Postfix → nonce-pipe → noncey.daemon   ←── REST API ──  noncey.client.chromeextension
                             │                                      │
                          SQLite                          auto-fill OTP field
                             │
                    noncey.client.androidapp (SMS OTPs)
```

## Repository layout (three sibling git repos)

All three repos live at the same directory level:

```
<basedir>  
  noncey\                          ← THIS REPO — umbrella: tests + docs
    tests\
      daemon\                      pytest tests for the daemon (test_01–test_05)
      client.chromeextension\      Playwright tests for the extension (test_10)
      run_smoke.sh                 Entry point
      conftest.py / pytest.ini
    README.md

  noncey.daemon\                   Linux daemon (Flask + SQLite + Postfix)
    app.py                         REST API + Flask app factory
    admin.py                       Admin UI Blueprint (/noncey/ prefix)
    db.py                          Shared DB helpers
    ingest.py                      Postfix pipe handler — extracts + stores nonces
    provision.py                   flask add-user / remove-user CLI commands
    schema.sql                     SQLite schema (CREATE TABLE IF NOT EXISTS)
    install.sh                     Idempotent installer — run as root on server
    noncey.conf.example            Config template
    requirements.txt
    templates/admin/               Jinja2 templates for admin UI
    ARCHITECTURE.md                Full architecture reference (authoritative)

  noncey.client.chromeextension\   Chrome extension (Manifest V3, vanilla JS)
    manifest.json
    background.js                  Service worker — polling, auth, state
    content.js                     Injected into pages — receives fill commands
    picker.js                      Visual OTP field picker mode
    popup/                         Toolbar popup (popup.html/js/css)
    options/                       Settings page (options.html/js/css)
```

GitHub remotes:

- noncey (this repo): https://github.com/fatihgey/noncey.git
- noncey.daemon:      https://github.com/fatihgey/noncey.daemon.git
- noncey.client.chromeextension: https://github.com/fatihgey/noncey.client.chromeextension.git
- noncey.client.androidapp: https://github.com/fatihgey/noncey.client.androidapp

---

## noncey.daemon — deployment note

`install.sh` is idempotent: stops the service, overwrites app files, runs DB
migrations, reinstalls pip deps, regenerates all config/unit files, and restarts.
Config at `/opt/noncey/daemon/etc/noncey.conf` is never touched by the installer
(created once manually). Safe to re-run after any source change.

## License

MIT — see [LICENSE](LICENSE).

# noncey

Automated email OTP relay. noncey intercepts one-time codes delivered by email
and makes them available to a Chrome extension, which can fill OTP fields
automatically or on demand.

```
incoming email
      │
      ▼
Postfix → nonce-pipe → noncey.daemon   ←──── REST API ────  noncey.client.chromeextension
                             │                                        │
                          SQLite                              auto-fill OTP field
```

---

## Repository layout

```
noncey/
  noncey.daemon/               Linux daemon (Flask + SQLite + Postfix integration)
    install.sh                 Installer — run once as root on the server
    noncey.conf.example        Config template
    ARCHITECTURE.md            Full architecture reference
    app.py / admin.py / db.py / ingest.py / provision.py / schema.sql
    requirements.txt
    templates/admin/           Admin web UI (Jinja2)

  noncey.client.chromeextension/  Chrome extension (Manifest V3, vanilla JS)
    manifest.json
    background.js / content.js / picker.js
    popup/                     Toolbar popup
    options/                   Settings page

  tests/                       Component test suite (pytest + Playwright)
    run_smoke.sh               Quick smoke test entry point
    daemon/                    Daemon tests (test_01 … test_05)
    client.chromeextension/    Extension tests (test_10)
```

---

## noncey.daemon — server installation

### Prerequisites (Ubuntu)

- Python 3.10+
- Apache2 with `mod_proxy`, `mod_proxy_http`
- Postfix with MySQL virtual maps (`postfix-mysql`)
- MySQL / MariaDB (for Postfix virtual maps)
- TLS certificate for the nonces subdomain (e.g. via Let's Encrypt)

### Steps

**1. Copy the source onto the server**

```bash
scp -r noncey.daemon/ user@server:/opt/noncey/daemon
```

Or clone directly on the server.

**2. Create the config file**

```bash
mkdir -p /opt/noncey/daemon/etc
cp /opt/noncey/daemon/noncey.conf.example /opt/noncey/daemon/etc/noncey.conf
editor /opt/noncey/daemon/etc/noncey.conf
```

Fill in every value marked `CHANGE_ME`.  The most important fields:

| Key | Description |
|---|---|
| `[general] domain` | The subdomain that receives nonce emails, e.g. `nonces.example.com` |
| `[general] admin_domain` | Your existing admin subdomain, e.g. `admin.example.com` |
| `[general] secret_key` | Random hex string — generate with `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `[mysql] *` | Postfix MySQL credentials (read-only user is sufficient) |
| `[tls] cert / key` | Paths to the TLS certificate for the nonces VirtualHost |

**3. Run the installer**

```bash
sudo bash /opt/noncey/daemon/install.sh
```

The installer is idempotent and safe to re-run after config changes.

It will:
- Create the `noncey` system user and directories under `/opt/noncey/daemon/`
- Create a Python virtualenv and install dependencies
- Write generated config files to `/opt/noncey/daemon/etc/` and symlink them into system directories
- Register the `nonce-pipe` Postfix transport (idempotent `master.cf` append + `postconf -e`)
- Create the Apache2 VirtualHost for `nonces.yourdomain.com` and enable it
- Install and enable the `noncey.service` systemd unit
- Install a cron job for archive cleanup

At the end it prints two manual steps — follow them to complete the Apache and Postfix configuration.

**4. Initialise the database and create the first user**

```bash
sudo -u noncey /opt/noncey/daemon/venv/bin/flask --app /opt/noncey/daemon/app.py init-db
sudo -u noncey /opt/noncey/daemon/venv/bin/flask --app /opt/noncey/daemon/app.py add-user <username>
```

Further users and providers can be managed through the admin web UI at
`https://admin.yourdomain.com/noncey/`.

---

## noncey.client.chromeextension — browser installation

The extension is written in vanilla JS with no build step.  Installation is
done by loading the unpacked directory directly into Chrome.

### Developer / personal install (recommended)

1. Open Chrome and navigate to `chrome://extensions`
2. Enable **Developer mode** (toggle, top-right)
3. Click **Load unpacked**
4. Select the `noncey.client.chromeextension/` directory

The noncey icon appears in the toolbar.  Updates to the JS files take effect
after clicking the **↺** (reload) button on the extensions page.

### Packaged install (.crx)

If you want to distribute the extension without the Chrome Web Store:

1. On `chrome://extensions`, click **Pack extension**
2. Set *Extension root directory* to `noncey.client.chromeextension/`
3. Leave *Private key file* empty on the first pack (Chrome generates one)
4. Click **Pack Extension** — Chrome produces `noncey.client.chromeextension.crx`
   and `noncey.client.chromeextension.pem` (keep the .pem for future updates)

The .crx can be distributed and drag-dropped onto `chrome://extensions` to
install, though Chrome may warn about third-party extensions depending on the
system policy.

> Note: Publishing to the Chrome Web Store requires a developer account and
> review process, which is outside the scope of this project.

### First-time configuration

1. Click the noncey toolbar icon → **⚙ Settings**
2. Enter your server URL (e.g. `https://nonces.example.com`) and credentials
3. Click **Log in**
4. Add a **Provider**: give it a tag, set the nonce start/end markers to match
   your email format, and add one or more sender / subject matchers
5. Add a **URL rule**: paste the URL (or a substring) of the page where you
   enter OTP codes, and use the field picker to click the OTP input field

The toolbar icon turns teal when the current tab matches a configured provider.

---

## Tests

See [`tests/`](tests/) for the full test suite.

```bash
cd tests
pip install -r requirements.txt

# Quick smoke (ingest + auth + nonces, no external deps):
./run_smoke.sh

# All daemon tests including admin UI:
./run_smoke.sh --all

# Include live Postfix delivery test:
NONCEY_TEST_MAIL=1 ./run_smoke.sh --all

# Include Chrome extension auto-fill test (requires: playwright install chromium):
NONCEY_TEST_EXTENSION=1 ./run_smoke.sh --all
```

The smoke tests are safe to run against a production installation — they use
the isolated `_test_` identity and clean up all data on exit.

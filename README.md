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

## Repositories

| Repo | Description |
|---|---|
| [noncey.daemon](https://github.com/fatihgey/noncey.daemon) | Server daemon — email ingestion, OTP extraction, REST API |
| [noncey.client.chromeextension](https://github.com/fatihgey/noncey.client.chromeextension) | Chrome extension — polls daemon, fills OTP fields |
| [noncey.client.androidapp](https://github.com/fatihgey/noncey.client.androidapp) | Android app — forwards SMS OTPs to the daemon |

## License

MIT — see [LICENSE](LICENSE).

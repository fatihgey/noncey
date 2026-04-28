# noncey — project CLAUDE.md

---

## Terminology and authorative data sources

When the user says "client" without qualification, assume the Chrome extension unless context implies Android.

Authoritative architecture reference: `noncey.daemon/ARCHITECTURE.md`
Authoritative extensive concept of Configuration: `noncey.daemon/CONFIGURATION.md`
Style GUIDE for deamon's UI: `noncey.daemon/STYLEGUIDE_UI.md`

## Troubleshooting policy

Confirm root cause first before proposing or executing solutions. Asking the user for additional info or probes is fine and expected.

---

## Versioning strategy

All noncey repos follow the same versioning scheme.

**Formal version** (`m.n.p`) — used wherever the ecosystem requires a clean version: package manifests, `manifest.json`, `build.gradle` `versionName`, npm/Gradle metadata, etc.

**Display version** (`m.n.p+kkkkkkk`) — the string shown inside the running components (UI, logs, about screens). Uses semver build-metadata syntax; the `+` suffix is ignored by comparators so it carries no precedence meaning.

**Deriving the version at build time:**

- `m.n.p` comes from the most recent git tag on the repo (format `vM.N.P` or `M.N.P`). If no tag exists, default to `1.0.0`.
- `kkkkkkk` is the 7-character short commit hash (`git rev-parse --short HEAD`).
- Canonical shell snippet: `git describe --tags --abbrev=0 2>/dev/null | sed 's/^v//' || echo "1.0.0"`

---

## Commit & push policy

After every change: commit and push to the relevant repo's GitHub remote.

---

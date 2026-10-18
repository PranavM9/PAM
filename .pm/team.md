# Team roster

Last updated: 2026-10-18 01:30 PDT

| Name | OS / machine | Docker (P0.6) | Other setup notes | Current task | Started |
|------|--------------|---------------|-------------------|--------------|---------|
| Pranav | macOS 12 Monterey | OK (Docker CLI works, confirmed 12:30) | Real Claude export at `demo/legacy-vault/imports/conversations.json` (70 convs, gitignored); holds the API keys | §10 housekeeping + T13 live check -> T16b demo kit -> compose healthcheck switch after T14 | 01:30 |
| Yogesh | Windows 11 | OK (verified by PM 01:30: build + container pytest) | Repo at WSL2 ~/code/pam (SETUP §1) | T14 REST API (t14/rest-api) -> T16c Windows | 01:30 |
| Aakash | Windows 11 | OK (confirmed 12:30) | Repo should live inside the WSL2 filesystem | e2e demo smoke test (if Pranav hasn't started it) -> T15 real-API wiring once T14 is pushed | 01:30 |

All three implement through Claude Code agents following SPEC §9.1.

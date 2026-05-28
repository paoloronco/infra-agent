# Security Policy

## Supported Versions

Only the latest commit on the `master` branch receives security fixes.
Older installs should be upgraded using `upgrade.sh` or `docker compose pull`.

| Version | Supported |
|---|---|
| `master` (latest) | ✅ Yes |
| Any pinned older commit | ❌ No — please upgrade |

---

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Use one of the following private channels:

- **GitHub private advisory (preferred):** [github.com/paoloronco/infra-agent/security/advisories/new](https://github.com/paoloronco/infra-agent/security/advisories/new)
- **Email:** info@paoloronco.it — subject line: `[infra-agent] Security Report`

Include as much detail as possible:
- A clear description of the vulnerability and its impact
- Steps to reproduce or a minimal proof-of-concept
- The component affected (backend, frontend, Docker image, installer)
- Any suggested fix if you have one

You will receive an acknowledgement within **72 hours**. A patched release will be targeted within **14 days** for critical issues.

---

## Scope

### In scope

| Category | Examples |
|---|---|
| **Authentication bypass** | Accessing the app or its API without valid credentials when auth is enabled |
| **SSH key exposure** | Reading, exfiltrating, or overwriting keys stored under `data/ssh_keys/` |
| **LLM API key leakage** | Recovering plaintext provider API keys stored encrypted in the database |
| **Command injection** | Bypassing the command validator to execute arbitrary shell commands on registered hosts |
| **Approval gate bypass** | Executing high-risk or critical commands without going through the approval flow |
| **Prompt injection via SSH output** | Using crafted SSH output to make the agent execute unintended actions |
| **Privilege escalation** | Gaining admin access from a regular user account, or unauthenticated access to admin endpoints |
| **CORS / CSRF** | Cross-origin attacks that exfiltrate data or perform actions on behalf of authenticated users |
| **Insecure deserialization / path traversal** | In the backup import, file upload, or attachment endpoints |
| **Cryptographic weaknesses** | In the Fernet key derivation, JWT secret generation, or Argon2id configuration |
| **Docker image vulnerabilities** | Exploitable CVEs in `paueron/infra-agent` base image layers that allow container escape or privilege escalation |

### Out of scope

| Category | Reason |
|---|---|
| Self-hosted network exposure | The operator is responsible for firewall rules, TLS, and access control at the network level |
| Authentication disabled by default | This is intentional for first-boot setup; the docs and installer explicitly instruct users to enable it |
| Missing rate limiting on specific endpoints | Low-severity rate limiting gaps without a realistic attack scenario |
| Theoretical attacks requiring physical access to the server | Out of the threat model for a self-hosted application |
| Vulnerabilities in third-party dependencies with no viable exploit path through this application | Report these upstream to the dependency maintainer |
| Scanner-generated reports without a working proof-of-concept | Generic findings without demonstrated impact |

---

## Security Design Notes

Understanding how the application is designed helps you evaluate whether a finding is a bug or an intentional trade-off.

### Authentication

Authentication is **disabled by default** to allow first-boot setup without a bootstrap login. It is intentionally designed this way and the documentation explicitly instructs users to enable it before exposing the app to a network. When enabled, sessions are JWT-based (configurable expiry, default 24 h) with Argon2id password hashing and account lockout after repeated failures.

### SSH keys

Private keys are generated as Ed25519 and stored under `backend/data/ssh_keys/` with `chmod 700`. They are never transmitted over the network and are not included in backup exports unless explicitly selected by the user.

### LLM API keys

Provider API keys are encrypted at rest using Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256). The encryption key is derived from the JWT secret stored in `data/secret_key.txt`. Losing `secret_key.txt` makes stored API keys unrecoverable and requires re-entry — this is intentional.

### Command validation

Every `ssh_run_command` call passes through a multi-layer validator before execution:
1. Forbidden pattern match (hard-blocked: `rm -rf /`, fork bombs, `mkfs`, `dd if=/dev/zero`, etc.)
2. Custom block list (operator-defined)
3. Risk classifier (critical / high / medium / low)
4. Approval gate — the agent pauses and requires explicit user action in the chat for high-risk and critical commands

The validator is a defence-in-depth layer, not the sole access control. SSH commands are still bound by the permissions of the `aiagent` OS user on the target host.

### Prompt injection

The agent includes a prompt injection detection layer (`agent/guardrails.py`) that inspects SSH command output for patterns that attempt to override the system prompt. Detected injections are logged and flagged, but the agent does not halt execution — it marks the output as potentially unsafe and continues.

### Backup and restore

Backup exports that include API keys or SSH keys require an encryption password. Without a password, sensitive fields are obfuscated (base64) but **not securely encrypted** — the documentation warns users of this. Import overwrites existing data in the selected sections and does not have a transactional rollback.

---

## Coordinated Disclosure

This project follows a **coordinated disclosure** process:

1. Researcher reports privately.
2. Maintainer acknowledges within 72 hours.
3. Fix is developed and tested on a private branch.
4. A patched release is cut and a GitHub Security Advisory is published simultaneously.
5. Credit is given to the reporter in the advisory unless they prefer to remain anonymous.

Please allow a reasonable window (14 days for critical, 30 days for high) before any public disclosure to give users time to upgrade.

---

## Hall of Fame

Researchers who responsibly disclose confirmed vulnerabilities will be credited here.

*(No entries yet.)*

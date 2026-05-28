# Changelog

All notable changes to this project are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

> Changes on `master` not yet tagged as a release.

### Added
- Docker image (`paueron/infra-agent`) published to Docker Hub via GitHub Actions CI/CD
- `Dockerfile` — multi-stage build: Node 20 Alpine compiles the React frontend, Python 3.12 slim runs the backend; Nginx serves the SPA and proxies API routes
- `docker-compose.yml` — single-command deploy with named volume for data persistence
- `docker/nginx.conf` — Nginx config for the container (SSE-aware, proxies `/api/`, `/ssh-keys`, `/systems`, and legacy routes)
- `docker/supervisord.conf` — runs Nginx + FastAPI under supervisord in one container
- `.dockerignore` — excludes `venv/`, `node_modules/`, `data/`, `.env`, and built artifacts from the image context
- `.github/workflows/docker-publish.yml` — builds and pushes `paueron/infra-agent:latest` + semver tags on every push to `master` and on `v*` tags
- `SECURITY.md` — responsible disclosure policy, in/out-of-scope table, security design notes for SSH keys, API key encryption, command validator, prompt injection detection
- `LICENSE` — MIT License
- `CONTRIBUTING.md` — dev setup guide, branch naming, conventional commits, PR process, testing instructions
- Docker page in the documentation site (`docs/index.html`) with prerequisites, quick start options, data persistence table, configuration reference, update/log commands, Caddy HTTPS example, and native vs Docker comparison table
- Docker installation section and `### Docker` subsection in `README.md`
- Docker entry in the `What You Get` list and Stack table in `README.md`

### Changed
- `docker-compose.yml` simplified — LLM provider API keys are now configured exclusively from the **Models** page in the web UI; no environment variables required beyond `CORS_ORIGINS`
- GitHub Actions workflow trigger updated from `main` to `master` to match the repository's default branch
- Docs site navigation extended from 12 to 13 pages; all `data-page` indices and `go()` references updated for the new Docker page
- Overview page TOC updated with Docker button and revised installation description
- Quick Start page updated with direct navigation links to Docker and Development Setup pages
- Contact email updated to `info@paoloronco.it` in `SECURITY.md`

---

## [2.0.0] – 2026-05-25

### Added
- **Agent memory management** — Honcho integration for cross-session long-term memory; configurable via `MEMORY_PROVIDER` (`local`, `honcho`, `hybrid`). Local memory uses SQLite; Honcho uses the remote workspace API
- Memory maintenance on startup: deduplication, compaction of older low-value entries, cleanup of records beyond `MEMORY_MAX_LOCAL_RECORDS`

### Fixed
- **Approval card flow** — approval cards in the chat now render and resolve correctly; chat input is blocked until the approval is acted on
- **Upgrader dirty checkout** — `upgrade.sh` now detects locally modified tracked files, saves a safety copy to `backend/data/pre-upgrade-local-changes-<timestamp>/` before resetting the checkout, then continues the upgrade without manual intervention
- Operations and deployment documentation aligned with actual runtime behaviour

---

## [2.0.0-rc] – 2026-05-21

Initial public repository snapshot. Features present at first release:

### Added
- FastAPI backend with LangGraph ReAct agent, Paramiko SSH toolkit, SQLAlchemy + SQLite persistence
- React 18 + Vite + Tailwind CSS frontend
- One-line Linux installer (`install.sh`) supporting `apt`, `dnf`/`yum`, and `pacman` families on `x86_64` and `aarch64`; configures systemd service and Nginx reverse proxy
- `upgrade.sh` — in-place upgrade: pulls latest code, backs up database, updates deps, rebuilds frontend, restarts service
- `uninstall.sh` — full removal with optional `--purge-deps`
- JWT authentication with Argon2id password hashing, account lockout, and optional first-boot bootstrap
- SSH key generation (Ed25519), host registration, and connection testing
- Multi-provider LLM support: Groq, OpenAI, Anthropic, Gemini, DeepSeek, Mistral, xAI, Perplexity, NVIDIA, OpenRouter, Zhipu, HuggingFace, Ollama
- Provider API keys encrypted at rest using Fernet (AES-128-CBC)
- Risky action approval flow: agent proposes command → approval card in chat → Approve / Deny / Other
- Command validator with forbidden-pattern blacklist, risk classifier, and configurable allow/block lists
- AI Safety presets: Strict, Balanced, Operator, Full Access
- Cron jobs — scheduled AI prompts with standard cron expression support
- Structured observability logs with category, level, event type, and JSON detail payload
- Token usage tracking per model with 14-day bar chart and model share breakdown
- Backup and restore (`.aib` format) with optional Fernet encryption for sensitive sections
- Agent memory (short-term per-session + long-term SQLite)
- Layered system prompt (9 ordered Markdown files under `backend/prompts/layers/`)
- Full documentation site (`docs/index.html`) — 12-page single-file SPA covering all features
- `start.ps1` — Windows PowerShell dev launcher
- No-password-by-default install (authentication disabled on first boot, enabled from Settings)
- Multiple installer stability fixes across `install.sh`

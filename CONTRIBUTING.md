# Contributing to Infra Agent

Thanks for taking the time to contribute. This document covers everything you need to go from zero to a merged pull request.

---

## Table of Contents

1. [Code of Conduct](#code-of-conduct)
2. [How to Report a Bug](#how-to-report-a-bug)
3. [How to Request a Feature](#how-to-request-a-feature)
4. [Development Setup](#development-setup)
5. [Project Structure](#project-structure)
6. [Branch Naming](#branch-naming)
7. [Commit Messages](#commit-messages)
8. [Submitting a Pull Request](#submitting-a-pull-request)
9. [Code Style](#code-style)
10. [Testing](#testing)
11. [Security Vulnerabilities](#security-vulnerabilities)

---

## Code of Conduct

Be respectful and constructive. Harassment, dismissive language, and personal attacks will not be tolerated.

---

## How to Report a Bug

1. Check [existing issues](https://github.com/paoloronco/infra-agent/issues) first.
2. Open a new issue using the **Bug report** template.
3. Include:
   - Steps to reproduce
   - Expected vs actual behaviour
   - Infra Agent version (git commit SHA or Docker image tag)
   - OS and install method (native / Docker / dev)
   - Relevant logs (`journalctl -u ai-agent -n 50` or `docker compose logs`)

---

## How to Request a Feature

Open an issue with the **Feature request** template. Describe the use case, not just the solution — it helps evaluate whether the feature fits the project's scope.

---

## Development Setup

### Prerequisites

| Tool | Minimum version |
|---|---|
| Python | 3.10 |
| Node.js | 20.19 or 22.12 |
| Git | any recent |

### 1. Fork and clone

```bash
git clone https://github.com/<your-username>/infra-agent.git
cd infra-agent/app
```

### 2. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
cp .env.example .env
python main.py                  # starts on http://localhost:8001
```

### 3. Frontend

```bash
cd frontend
npm ci
npm run dev                     # starts on http://localhost:5173
```

### 4. First-time setup

Open **http://localhost:5173**, go to **Models**, and add at least one LLM provider API key to test the agent.

### Windows shortcut

```powershell
.\start.ps1
```

Launches both backend and frontend in separate terminals.

---

## Project Structure

```
app/
├── backend/
│   ├── main.py              # FastAPI entry point
│   ├── agent_loader.py      # LangGraph agent factory
│   ├── config.py            # All settings (pydantic-settings)
│   ├── routers/             # One file per API domain
│   ├── agent/               # Guardrails, state, checkpointing
│   ├── tools/               # Tool registry and command validator
│   ├── memory/              # Short-term and long-term memory
│   └── prompts/layers/      # 9 ordered Markdown files composing the system prompt
├── frontend/
│   ├── src/pages/           # One component per route
│   ├── src/components/      # Shared UI components
│   └── src/api.js           # All API calls (Axios + fetch)
├── docker/                  # nginx.conf, supervisord.conf for Docker
├── deploy/                  # systemd service unit, Nginx config template
└── docs/                    # Documentation site (single index.html)
```

---

## Branch Naming

```
feat/<short-description>       # new feature
fix/<short-description>        # bug fix
docs/<short-description>       # documentation only
chore/<short-description>      # tooling, deps, build changes
refactor/<short-description>   # code change with no functional impact
```

Examples:

```
feat/cron-job-history
fix/approval-card-render
docs/docker-setup-guide
chore/upgrade-langchain-2.x
```

---

## Commit Messages

This project uses [Conventional Commits](https://www.conventionalcommits.org/).

```
<type>(<optional scope>): <short imperative summary>

<optional body — what and why, not how>

<optional footer — breaking changes, issue references>
```

| Type | Use for |
|---|---|
| `feat` | A new feature visible to users |
| `fix` | A bug fix |
| `docs` | Documentation only |
| `chore` | Build scripts, deps, CI, no production code change |
| `refactor` | Code restructure without behaviour change |
| `perf` | Performance improvement |
| `test` | Adding or fixing tests |
| `revert` | Reverting a previous commit |

**Good examples:**

```
feat(memory): add Honcho provider for cross-session long-term memory
fix(approval): prevent chat input from unblocking before approval resolves
docs(docker): add CORS configuration reference to Docker page
chore: upgrade langchain to 1.2.17
```

**Breaking changes** — add `BREAKING CHANGE:` in the footer:

```
feat(auth): replace localStorage token with HttpOnly cookie

BREAKING CHANGE: clients must send credentials via cookie, not Authorization header.
```

---

## Submitting a Pull Request

1. **Open an issue first** for anything non-trivial so the approach can be discussed before you invest time coding.
2. Fork the repository and create your branch from `master`.
3. Make your changes. Keep each PR focused on a single concern.
4. Run the tests (see [Testing](#testing)).
5. Update documentation if your change affects user-visible behaviour:
   - `README.md` for installation or feature changes
   - `docs/index.html` for the documentation site
   - `CHANGELOG.md` — add an entry under `[Unreleased]`
6. Open a pull request against `master`. Fill in the PR template.

### PR checklist

- [ ] Tests pass locally
- [ ] No new linter warnings in changed files
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] Documentation updated if behaviour changed
- [ ] No hardcoded secrets, API keys, or personal data

---

## Code Style

### Python (backend)

- Follow [PEP 8](https://peps.python.org/pep-0008/).
- Type hints on all function signatures.
- Docstrings only where the purpose of a function is not obvious from its name and types alone.
- Avoid bare `except:` — always catch specific exception types.
- Keep route handlers thin: business logic belongs in service functions, not directly in routers.

### JavaScript / React (frontend)

- Functional components with hooks only — no class components.
- Props are not validated with PropTypes (the project does not use them); rely on clear naming instead.
- All API calls go through `src/api.js` — do not call `fetch` or `axios` directly from components.
- Keep components under ~300 lines; split into sub-components when they grow.

### General

- No commented-out code in commits.
- No `console.log` or `print` debug statements in commits.
- Prefer clarity over cleverness — code is read more than it is written.

---

## Testing

### Backend

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest test_*.py -v
```

### Frontend end-to-end (Playwright)

```bash
cd frontend
npm run test:e2e:approval
```

This builds the frontend, installs Chromium, and runs the approval flow test.

### Manual smoke test

After making changes, verify the golden path:

1. Start the app (`start.ps1` or manual backend + frontend).
2. Add an LLM provider in **Models** and click **Test**.
3. Register an SSH host in **SSH Manager** and click **Test**.
4. Open **Chat**, send a read-only prompt (e.g. *"Check disk usage"*) — confirm the agent responds with real SSH output.
5. Send a risky prompt (e.g. *"Delete /tmp/test.txt"*) — confirm the approval card appears and chat input is blocked.

---

## Security Vulnerabilities

Do **not** open a public issue for security vulnerabilities. See [SECURITY.md](.github/SECURITY.md) for the private disclosure process.

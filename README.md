# Infra Agent

An open-source AI agent for diagnosing and managing remote Linux hosts over SSH.

Ask in plain English, choose a registered host, and the agent connects through SSH,
runs diagnostics, reads logs, and reports back with real system data. Risky actions
such as deleting files or restarting services require explicit approval in the chat
before they are executed.

![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?style=flat&logo=fastapi)
![React](https://img.shields.io/badge/React-18-61DAFB?style=flat&logo=react)
![LangGraph](https://img.shields.io/badge/LangGraph-1.x-FF6B6B?style=flat)
![License](https://img.shields.io/badge/license-MIT-blue?style=flat)

## What You Get

- AI chat for SSH troubleshooting and host operations.
- SSH key generation, host registration, and host hierarchy management.
- Read-only diagnostics for services, logs, resources, disks, processes, and network.
- Approval flow for risky SSH actions: proposed command, Approve, Deny, Other.
- Persistent chats with per-chat host context.
- Model provider management from the UI.
- Backup and restore for app data.
- Systemd and Nginx production install script.

---

## Quick Start

### Production Install

Native Linux install:

```bash
curl -fsSL https://raw.githubusercontent.com/paoloronco/infra-agent/master/install.sh | sudo bash
```

The one-line installer uses defaults automatically: `/opt/ai-agent`, Nginx on port `80`, and the first free backend port starting from `8000`. It builds into a staging directory, preserves `backend/data` and `.env` on reinstall, health-checks the backend before it reports success, and restores the previous install tree if cutover fails. Authentication is disabled on first boot; enable it from Settings when the UI is ready to require login.

Supported native targets:

| Area | Supported |
|---|---|
| Package manager family | `apt` (Debian/Ubuntu), `dnf`/`yum` (Fedora/RHEL family), `pacman` (Arch family) |
| CPU | glibc Linux `x86_64` or `aarch64` |
| Python | Python 3.10+ available from the OS/package set |
| Runtime | running systemd recommended; background fallback is available for WSL/container-like environments |

The installer does not mutate the machine-wide Node.js installation. It downloads a checksum-verified Node.js build runtime into the install tree for the Vite build and uses `npm ci` from `frontend/package-lock.json`.

Useful non-interactive examples:

```bash
curl -fsSL https://raw.githubusercontent.com/paoloronco/infra-agent/master/install.sh \
  | sudo bash -s -- --yes --domain infra.example.com

sudo bash /opt/ai-agent/install.sh --yes --no-nginx --runtime background --backend-port 8000
sudo bash /opt/ai-agent/install.sh --yes --ref v1.2.3
```

On systems without running systemd, background mode writes logs to `/var/log/ai-agent/backend.log`. For a production container deployment, prefer a versioned OCI image plus an external supervisor/orchestrator instead of treating background mode as a reboot-safe service manager.

Alternative manual install:

```bash
git clone https://github.com/paoloronco/infra-agent.git
cd infra-agent
sudo bash install.sh
```

Open the printed URL, then:

1. Go to **Models** and add at least one provider API key.
2. Go to **SSH Manager**.
3. Click **Add host**.
4. Generate the SSH setup command.
5. Run that command on the target host.
6. Test the SSH connection.
7. Start chatting.

Example prompts:

```text
Is nginx running on web-prod?
Show disk usage on db-prod.
Read the last 100 journal entries for nginx.
Delete /root/test1.txt.
```

The delete request should not run immediately. The chat must show the proposed
command and an approval card with **Approve**, **Deny**, and **Other**.

### Local Development

Windows:

```powershell
.\start.ps1
```

Manual setup:

Requires Python 3.10+ and Node.js 20.19+ or 22.12+ for the Vite frontend build.

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173.

---

## Documentation

<details>
<summary><strong>Project Structure</strong></summary>

```text
.
|-- backend/
|   |-- main.py                  # FastAPI app
|   |-- agent_loader.py          # LangGraph agent entry point
|   |-- ssh_toolkit.py           # Paramiko SSH toolkit
|   |-- db.py                    # SQLAlchemy setup and migrations
|   |-- models_db.py             # ORM models
|   |-- auth.py                  # JWT auth and account lockout
|   |-- ssh_key_manager.py       # SSH key generation and persistence
|   |-- routers/
|   |   |-- chat.py              # Chat, SSE, risky action approvals
|   |   |-- backup.py            # Backup export and restore
|   |   |-- models_config.py     # LLM provider configuration
|   |   |-- systems.py           # Registered hosts
|   |   |-- ssh.py               # SSH key and test endpoints
|   |   |-- logs.py              # Observability logs
|   |   `-- usage.py             # Token usage stats
|   |-- tools/
|   |   |-- registry.py          # Tool registry
|   |   `-- validator.py         # Command risk classification
|   |-- prompts/layers/          # Layered system prompt
|   `-- memory/                  # Short and long-term context
|
|-- frontend/
|   |-- src/
|   |   |-- pages/
|   |   |   |-- Chat.jsx
|   |   |   |-- SshManager.jsx
|   |   |   |-- Models.jsx
|   |   |   `-- Logs.jsx
|   |   |-- components/
|   |   |-- api.js
|   |   `-- context/
|   `-- tests/
|
|-- deploy/
|   |-- ai-agent.service
|   `-- nginx.conf.template
|
|-- install.sh
|-- upgrade.sh
|-- uninstall.sh
`-- start.ps1
```

</details>

<details>
<summary><strong>Stack</strong></summary>

| Layer | Technology |
|---|---|
| Agent | LangGraph ReAct agent |
| Backend | FastAPI, Uvicorn, SQLAlchemy, SQLite |
| Frontend | React 18, Vite, Tailwind CSS |
| SSH | Paramiko |
| Models | Groq, OpenAI, Anthropic, Gemini, Ollama, OpenAI-compatible providers |
| Auth | JWT, optional login, account lockout |
| Deployment | systemd, Nginx |

</details>

<details>
<summary><strong>Host Setup</strong></summary>

1. Open **SSH Manager**.
2. Click **Add host**.
3. Choose **AI Agent setup** for the easiest path.
4. Enter host, port, username, and system name.
5. Generate the setup command.
6. Run the command on the target host as root or with sudo.
7. Test the connection from the app.
8. Save the host.

Private keys are stored under:

```text
backend/data/ssh_keys/
```

Registered hosts are available to the AI by system name. Each chat can lock to a
specific host so different conversations can target different machines safely.

</details>

<details>
<summary><strong>Risky SSH Action Approval</strong></summary>

Read-only requests run normally:

```text
Check nginx status.
Show memory usage.
Read /var/log/nginx/error.log.
List running processes.
```

Risky requests must pause for approval:

```text
Delete /root/test1.txt.
Restart nginx.
Install htop.
Edit /etc/nginx/nginx.conf.
Kill process 1234.
```

Expected flow:

1. The agent identifies the risky command.
2. The command is shown in the chat.
3. The approval card appears with **Approve**, **Deny**, and **Other**.
4. Normal chat input is blocked until the approval is resolved.
5. **Approve** executes the exact pending command over SSH.
6. **Deny** cancels the action.
7. **Other** lets you provide alternate instructions.
8. The real SSH output is shown after execution.

</details>

<details>
<summary><strong>Model Providers</strong></summary>

Go to **Models** in the UI to configure provider keys. Prefer the UI over editing
`.env` manually.

Supported providers include:

- Groq
- OpenAI
- Anthropic
- Gemini
- DeepSeek
- Mistral AI
- xAI
- Perplexity
- NVIDIA
- OpenRouter
- Zhipu
- Hugging Face
- Ollama

API keys are encrypted in the database. Backup and restore normalize keys so the
runtime sends decrypted provider keys, not encrypted database tokens.

</details>

<details>
<summary><strong>Backup and Restore</strong></summary>

Use **Backup** in the UI to export or restore app data.

Sensitive exports that include API keys or SSH keys require encryption. Restored
API keys are normalized and re-encrypted for the current installation.

Recommended before upgrades:

1. Export a backup.
2. Store it somewhere outside the app directory.
3. Run the upgrade.
4. Test model provider connectivity.
5. Test one SSH host.

</details>

<details>
<summary><strong>Upgrade</strong></summary>

Production upgrade:

```bash
sudo bash /opt/ai-agent/upgrade.sh
```

The upgrader pulls from `origin/master`, updates backend dependencies, rebuilds
the frontend, restarts the service, and prints recent logs if startup fails.

Useful service commands:

```bash
sudo systemctl status ai-agent
sudo systemctl restart ai-agent
sudo journalctl -u ai-agent -f
```

Complete uninstall:

```bash
sudo bash /opt/ai-agent/uninstall.sh --yes
```

Remove the app plus packages installed specifically for it. The uninstaller keeps base system packages such as `curl`, `ca-certificates`, `git`, and `iproute2`:

```bash
sudo bash /opt/ai-agent/uninstall.sh --yes --purge-deps
```

</details>

<details>
<summary><strong>API Overview</strong></summary>

Health:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/info` | App metadata |

Chat:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/chats` | List chats |
| `POST` | `/api/chats` | Create chat |
| `GET` | `/api/chats/{id}` | Get chat with messages |
| `PATCH` | `/api/chats/{id}` | Update title, model, or host |
| `DELETE` | `/api/chats/{id}` | Delete chat |
| `POST` | `/api/chats/{id}/messages` | Send message with SSE stream |
| `POST` | `/api/chats/{id}/approvals/{approval_id}` | Resolve risky action approval |

SSH and systems:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/ssh-keys` | List SSH keys |
| `POST` | `/ssh-key` | Generate key |
| `DELETE` | `/ssh-key/{id}` | Delete key |
| `POST` | `/ssh-test` | Test SSH connectivity |
| `GET` | `/systems` | List registered hosts |
| `POST` | `/systems` | Create or update host |
| `DELETE` | `/systems/{id}` | Delete host |

Models:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/models/providers` | List provider status |
| `PUT` | `/api/models/providers/{id}` | Save provider config |
| `POST` | `/api/models/providers/{id}/test` | Test provider |

</details>

<details>
<summary><strong>Security Notes</strong></summary>

- The agent can only target registered hosts.
- SSH private keys are stored locally with restrictive permissions.
- Tool output is sanitized before it is sent back to the model.
- Risky commands require explicit UI approval.
- One pending approval is allowed per chat.
- API keys are encrypted at rest.
- Optional app login can be enabled from Settings.
- Prompt injection patterns are detected and logged.

</details>

<details>
<summary><strong>Architecture</strong></summary>

Chat streaming uses a background task so messages are not lost if the browser
disconnects.

```text
POST /api/chats/{id}/messages
|
|-- Save user message
|-- Create assistant placeholder
|-- Start background AI task
|-- Stream events through SSE
|
`-- Background task persists final result to DB
```

The system prompt is composed from ordered Markdown layers:

```text
00_core_identity
01_operational_rules
02_tool_policies
03_safety_policies
04_output_format
05_recovery_behaviors
06_failure_handling
07_attachment_handling
```

</details>

<details>
<summary><strong>Troubleshooting</strong></summary>

Backend does not start:

```bash
sudo journalctl -u ai-agent -n 80 --no-pager
```

Frontend is stale after upgrade:

```bash
sudo systemctl restart ai-agent
sudo systemctl reload nginx
```

No API key configured:

1. Open **Models**.
2. Add a provider API key.
3. Click **Test**.

SSH connection fails:

```bash
ping <host>
ssh <user>@<host> -p <port>
sudo systemctl status ssh
```

Approval card does not appear for risky actions:

1. Refresh the chat.
2. Check `/api/chats/{id}` and confirm `pending_approval` is present.
3. Check backend logs with `sudo journalctl -u ai-agent -n 80 --no-pager`.
4. Confirm the risky action was proposed as a shell command.

</details>

## License

MIT

"""SSH key generation, persistence and setup-script helpers."""
import json
import os
import re
import secrets
import stat
import uuid
from datetime import datetime
from utils import utcnow
from pathlib import Path
from typing import Any, Dict, List, Optional

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

KEYS_DIR = Path(__file__).resolve().parent / "data" / "ssh_keys"
KEYS_INDEX = KEYS_DIR / "keys_index.json"
USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def _ensure_keys_dir() -> None:
    KEYS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(KEYS_DIR, stat.S_IRWXU)
    except Exception:
        pass


def _detect_private_key_format(path: str) -> str:
    try:
        # Reconstruct from safe base using only the filename component so that
        # any directory traversal in `path` is neutralised before filesystem access.
        safe_path = (KEYS_DIR / Path(path).name).resolve()
        if not safe_path.is_relative_to(KEYS_DIR.resolve()):
            return "missing"
        text = safe_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return "missing"
    if "BEGIN OPENSSH PRIVATE KEY" in text:
        return "openssh"
    if "BEGIN RSA PRIVATE KEY" in text:
        return "pem-rsa"
    return "unknown"


def validate_private_key_file(path: str) -> Dict[str, Any]:
    """Return whether Paramiko can load a private key file."""
    # Sanitise before any filesystem access: rebuild from safe base + filename only.
    safe_path = (KEYS_DIR / Path(path).name).resolve()
    if not safe_path.is_relative_to(KEYS_DIR.resolve()):
        return {"valid": False, "key_type": "unknown", "private_key_format": "missing", "error": "path outside keys directory"}
    path = str(safe_path)
    fmt = _detect_private_key_format(path)
    loaders = (
        ("ssh-ed25519", paramiko.Ed25519Key),
        ("ssh-rsa", paramiko.RSAKey),
        ("ecdsa-sha2-nistp256", paramiko.ECDSAKey),
    )
    errors: List[str] = []
    for key_type, loader in loaders:
        try:
            loader.from_private_key_file(path)
            return {
                "valid": True,
                "key_type": key_type,
                "private_key_format": fmt,
                "error": None,
            }
        except Exception as exc:
            errors.append(f"{key_type}: {exc}")
    return {
        "valid": False,
        "key_type": "unknown",
        "private_key_format": fmt,
        "error": "; ".join(errors[:3]),
    }


def _load_index() -> List[Dict[str, Any]]:
    if not KEYS_INDEX.exists():
        return []
    try:
        entries = json.loads(KEYS_INDEX.read_text(encoding="utf-8"))
        changed = False
        for entry in entries:
            if not entry.get("ssh_key_path"):
                entry["ssh_key_path"] = entry.get("private_key_path", "").replace("\\", "/")
                changed = True
            if not entry.get("key_type"):
                public_key = entry.get("public_key", "")
                entry["key_type"] = public_key.split(" ", 1)[0] if public_key else "unknown"
                changed = True
            if not entry.get("private_key_format"):
                entry["private_key_format"] = _detect_private_key_format(entry.get("private_key_path", ""))
                changed = True
            if not entry.get("setup_token"):
                entry["setup_token"] = secrets.token_urlsafe(32)
                changed = True
        if changed:
            KEYS_INDEX.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        return entries
    except Exception:
        return []


def _save_index(index: List[Dict[str, Any]]) -> None:
    _ensure_keys_dir()
    KEYS_INDEX.write_text(json.dumps(index, indent=2), encoding="utf-8")
    try:
        os.chmod(KEYS_INDEX, stat.S_IRUSR | stat.S_IWUSR)  # 600 — owner read/write only
    except Exception:
        pass


def list_ssh_keys() -> List[Dict[str, Any]]:
    return _load_index()


def get_ssh_key(key_id: str) -> Optional[Dict[str, Any]]:
    return next((k for k in _load_index() if k["key_id"] == key_id), None)


def get_ssh_key_by_setup_token(setup_token: str) -> Optional[Dict[str, Any]]:
    if not setup_token or len(setup_token) < 24:
        return None
    for entry in _load_index():
        if secrets.compare_digest(entry.get("setup_token", ""), setup_token):
            return entry
    return None


def _key_file_paths(entry: Dict[str, Any]) -> List[Path]:
    paths: List[Path] = []
    for path_key in ("private_key_path", "ssh_key_path"):
        raw_path = (entry.get(path_key) or "").strip()
        if not raw_path:
            continue
        path = Path(raw_path)
        if path not in paths:
            paths.append(path)
        pub_path = Path(f"{raw_path}.pub")
        if pub_path not in paths:
            paths.append(pub_path)
    return paths


def delete_ssh_key(key_id: str) -> Optional[Dict[str, Any]]:
    index = _load_index()
    entry = next((k for k in index if k["key_id"] == key_id), None)
    if not entry:
        return None

    deleted_files: List[str] = []
    missing_files: List[str] = []
    failed_files: List[str] = []

    for path in _key_file_paths(entry):
        if not path.exists():
            missing_files.append(str(path))
            continue
        try:
            path.unlink()
        except Exception as exc:
            failed_files.append(f"{path}: {exc}")
            continue
        if path.exists():
            failed_files.append(f"{path}: still exists after deletion")
        else:
            deleted_files.append(str(path))

    if failed_files:
        raise OSError("Unable to delete SSH key file(s): " + "; ".join(failed_files))

    _save_index([k for k in index if k["key_id"] != key_id])
    if get_ssh_key(key_id):
        raise OSError(f"SSH key {key_id} still exists in the key index after deletion")

    return {
        "entry": entry,
        "deleted_files": deleted_files,
        "missing_files": missing_files,
    }


def _validate_setup_username(username: str) -> str:
    value = (username or "aiagent").strip().lower()
    if not USERNAME_RE.match(value):
        raise ValueError("Username must be lowercase and contain only letters, digits, '_' or '-'")
    return value


def _build_destination_command(public_key: str, dest_os: str) -> str:
    if dest_os in ("linux", "macos"):
        return (
            "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
            f'printf "%s\\n" "{public_key}" >> ~/.ssh/authorized_keys && '
            "chmod 600 ~/.ssh/authorized_keys"
        )
    if dest_os in ("windows10", "windows11"):
        return (
            f'$key = "{public_key}"\n'
            '$sshDir = "$env:USERPROFILE\\.ssh"\n'
            'if (-not (Test-Path $sshDir)) { New-Item -ItemType Directory -Path $sshDir | Out-Null }\n'
            'Add-Content -Path "$sshDir\\authorized_keys" -Value $key\n'
            'icacls "$sshDir\\authorized_keys" /inheritance:r /grant:r "$($env:USERNAME):(R,W)"'
        )
    return f'printf "%s\\n" "{public_key}" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'


def _generate_ed25519_private_key() -> tuple[str, str]:
    private_key = ed25519.Ed25519PrivateKey.generate()
    private_text = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_text = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode("ascii")
    return private_text, public_text


def build_ai_agent_setup_script(entry: Dict[str, Any]) -> str:
    username = _validate_setup_username(entry.get("username") or "aiagent")
    public_key = (entry.get("public_key") or "").strip()
    if not public_key.startswith(("ssh-ed25519 ", "ssh-rsa ")):
        raise ValueError("Stored public key is not a supported OpenSSH public key")

    return f"""#!/bin/bash
set -eu

AI_USER='{username}'
PUBLIC_KEY=$(cat <<'AI_AGENT_PUBLIC_KEY'
{public_key}
AI_AGENT_PUBLIC_KEY
)

ok() {{ printf '\\033[0;32mOK\\033[0m %s\\n' "$1"; }}
info() {{ printf '\\033[0;34m..\\033[0m %s\\n' "$1"; }}
warn() {{ printf '\\033[0;33mWARN\\033[0m %s\\n' "$1"; }}
fail() {{ printf '\\033[0;31mERROR\\033[0m %s\\n' "$1" >&2; exit 1; }}
has() {{ command -v "$1" >/dev/null 2>&1; }}

[ "$(id -u)" = "0" ] || fail "Run this command as root on the target VM/CT."

OS_ID="unknown"
OS_LIKE=""
[ -r /etc/os-release ] && . /etc/os-release && OS_ID="${{ID:-unknown}}" && OS_LIKE="${{ID_LIKE:-}}"
CONTAINER="no"
[ -f /.dockerenv ] && CONTAINER="yes"
[ -f /run/.containerenv ] && CONTAINER="yes"
grep -qaE 'docker|lxc|container|kubepods' /proc/1/cgroup 2>/dev/null && CONTAINER="yes" || true

info "AI Agent SSH setup"
info "Detected OS: $OS_ID ${{OS_LIKE:+($OS_LIKE)}}, container: $CONTAINER"

install_pkg() {{
  pkg="$1"
  if has apk; then apk add --no-cache "$pkg" >/dev/null 2>&1 || return 1
  elif has apt-get; then apt-get update >/dev/null 2>&1 && DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg" >/dev/null 2>&1 || return 1
  elif has dnf; then dnf install -y "$pkg" >/dev/null 2>&1 || return 1
  elif has yum; then yum install -y "$pkg" >/dev/null 2>&1 || return 1
  elif has pacman; then pacman -Sy --noconfirm "$pkg" >/dev/null 2>&1 || return 1
  else return 1
  fi
}}

ensure_user() {{
  if id "$AI_USER" >/dev/null 2>&1; then ok "User $AI_USER already exists"; return; fi
  shell="/bin/sh"; [ -x /bin/bash ] && shell="/bin/bash"
  if has useradd; then
    useradd -m -s "$shell" "$AI_USER"
  elif has adduser; then
    adduser -D -h "/home/$AI_USER" -s "$shell" "$AI_USER" 2>/dev/null || adduser --disabled-password --gecos "" --home "/home/$AI_USER" --shell "$shell" "$AI_USER"
  else
    fail "Cannot create user: neither useradd nor adduser is available."
  fi
  passwd -l "$AI_USER" >/dev/null 2>&1 || true
  ok "Created locked key-only user $AI_USER"
}}

ensure_sudo() {{
  if ! has sudo; then warn "sudo is not installed; trying to install it"; install_pkg sudo || warn "Could not install sudo automatically"; fi
  if getent group sudo >/dev/null 2>&1; then
    if has usermod; then usermod -aG sudo "$AI_USER"; elif has addgroup; then addgroup "$AI_USER" sudo; fi
    ok "Added $AI_USER to sudo group"
  elif getent group wheel >/dev/null 2>&1; then
    if has usermod; then usermod -aG wheel "$AI_USER"; elif has addgroup; then addgroup "$AI_USER" wheel; fi
    ok "Added $AI_USER to wheel group"
  else
    warn "No sudo/wheel group found"
  fi
  if has sudo && [ -d /etc/sudoers.d ]; then
    {{
      printf '# AI Agent remote operator profile\\n'
      printf '# Grants non-interactive sudo for diagnostics, log access, and service operations.\\n'
      printf '# Effective scope: systemctl status/show/list-units/start/stop/restart/reload/enable/disable/daemon-reload; journalctl; dmesg; uptime/free/df/du/top/ps/pgrep/pidstat/iostat/vmstat/lsblk/mount/findmnt; ping/traceroute/tracepath/dig/nslookup/host/curl/wget/ss/ip/ethtool/nmcli/resolvectl; log readers under /var/log, /opt/*/logs, /srv/*/logs.\\n'
      printf '%s ALL=(ALL) NOPASSWD:ALL\\n' "$AI_USER"
    }} > "/etc/sudoers.d/90-ai-agent-$AI_USER"
    chmod 440 "/etc/sudoers.d/90-ai-agent-$AI_USER"
    if has visudo && ! visudo -c -f "/etc/sudoers.d/90-ai-agent-$AI_USER" >/dev/null 2>&1; then
      rm -f "/etc/sudoers.d/90-ai-agent-$AI_USER"
      warn "sudoers validation failed; removed passwordless sudo file"
    else
      ok "Configured passwordless sudo"
    fi
  fi
}}

install_authorized_key() {{
  home_dir=$(getent passwd "$AI_USER" | cut -d: -f6)
  [ -n "$home_dir" ] || home_dir="/home/$AI_USER"
  ssh_dir="$home_dir/.ssh"; auth_keys="$ssh_dir/authorized_keys"
  mkdir -p "$ssh_dir"; touch "$auth_keys"
  if grep -qxF "$PUBLIC_KEY" "$auth_keys"; then ok "Public key already installed"; else printf '%s\\n' "$PUBLIC_KEY" >> "$auth_keys"; ok "Installed OpenSSH public key"; fi
  chown -R "$AI_USER:$AI_USER" "$ssh_dir" 2>/dev/null || chown -R "$AI_USER" "$ssh_dir"
  chmod 700 "$ssh_dir"; chmod 600 "$auth_keys"
  case "$PUBLIC_KEY" in ssh-ed25519\\ *) ok "Key format: ssh-ed25519 / OpenSSH" ;; ssh-rsa\\ *) ok "Key format: ssh-rsa / OpenSSH" ;; *) fail "Unsupported public key format" ;; esac
}}

set_sshd_option() {{
  key="$1"; value="$2"; file="$3"
  if grep -q "^[#[:space:]]*$key[[:space:]]" "$file"; then sed -i "s|^[#[:space:]]*$key[[:space:]].*|$key $value|" "$file"; else printf '\\n%s %s\\n' "$key" "$value" >> "$file"; fi
}}

reload_ssh() {{
  if has systemctl; then
    systemctl reload sshd >/dev/null 2>&1 && return 0
    systemctl reload ssh >/dev/null 2>&1 && return 0
    systemctl restart sshd >/dev/null 2>&1 && return 0
    systemctl restart ssh >/dev/null 2>&1 && return 0
  fi
  if has rc-service; then rc-service sshd reload >/dev/null 2>&1 && return 0; rc-service sshd restart >/dev/null 2>&1 && return 0; fi
  if has service; then service sshd reload >/dev/null 2>&1 && return 0; service ssh reload >/dev/null 2>&1 && return 0; service sshd restart >/dev/null 2>&1 && return 0; service ssh restart >/dev/null 2>&1 && return 0; fi
  [ -x /etc/init.d/sshd ] && /etc/init.d/sshd reload >/dev/null 2>&1 && return 0
  [ -x /etc/init.d/ssh ] && /etc/init.d/ssh reload >/dev/null 2>&1 && return 0
  return 1
}}

harden_sshd() {{
  conf="/etc/ssh/sshd_config"
  [ -f "$conf" ] || {{ warn "sshd_config not found; skipping SSH hardening"; return 0; }}
  cp "$conf" "$conf.ai-agent.bak"
  set_sshd_option PubkeyAuthentication yes "$conf"
  set_sshd_option AuthorizedKeysFile ".ssh/authorized_keys" "$conf"
  set_sshd_option PasswordAuthentication no "$conf"
  set_sshd_option PermitRootLogin no "$conf"
  if has sshd && ! sshd -t >/dev/null 2>&1; then cp "$conf.ai-agent.bak" "$conf"; warn "SSH hardening failed validation; restored original sshd_config"; return 0; fi
  reload_ssh && ok "SSH service reloaded" || warn "Could not reload SSH automatically; config will apply after SSH restart"
}}

ensure_user
ensure_sudo
install_authorized_key
harden_sshd

if has sudo; then su -s /bin/sh "$AI_USER" -c "sudo -n true" >/dev/null 2>&1 && ok "Verified passwordless sudo" || warn "Could not verify passwordless sudo in this environment"; fi

host_ip=$(hostname -I 2>/dev/null | awk '{{print $1}}' || true)
printf '\\nSetup complete. Return to the AI Agent app and click Test Connection.\\n'
printf 'User: %s\\n' "$AI_USER"
[ -n "$host_ip" ] && printf 'Detected IP: %s\\n' "$host_ip"
"""


def generate_ssh_key_pair(
    comment: Optional[str] = None,
    dest_os: str = "linux",
    host: Optional[str] = None,
    username: Optional[str] = None,
    system_name: Optional[str] = None,
    port: int = 22,
) -> Dict[str, Any]:
    _ensure_keys_dir()
    comment_text = (comment.strip() if comment and comment.strip() else "ai-agent-key")
    safe_username = _validate_setup_username(username or "aiagent") if username else ""

    private_key_text, public_without_comment = _generate_ed25519_private_key()
    public_key = f"{public_without_comment} {comment_text}"
    key_id = str(uuid.uuid4())
    key_name = f"ai_agent_{key_id[:8]}"
    setup_token = secrets.token_urlsafe(32)

    priv_path = KEYS_DIR / key_name
    priv_path.write_text(private_key_text, encoding="utf-8")
    try:
        os.chmod(priv_path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass

    validation = validate_private_key_file(str(priv_path))
    if not validation["valid"]:
        try:
            priv_path.unlink()
        except Exception:
            pass
        raise ValueError(f"Generated SSH key failed Paramiko validation: {validation['error']}")

    pub_path = KEYS_DIR / f"{key_name}.pub"
    pub_path.write_text(public_key + "\n", encoding="utf-8")

    destination_command = _build_destination_command(public_key, dest_os)
    ssh_key_path = str(priv_path).replace("\\", "/")

    entry: Dict[str, Any] = {
        "key_id": key_id,
        "key_name": key_name,
        "comment": comment_text,
        "dest_os": dest_os,
        "host": host or "",
        "port": port,
        "username": safe_username,
        "system_name": system_name or "",
        "public_key": public_key,
        "private_key_path": str(priv_path),
        "ssh_key_path": ssh_key_path,
        "key_type": validation["key_type"],
        "private_key_format": validation["private_key_format"],
        "setup_token": setup_token,
        "destination_command": destination_command,
        "created_at": utcnow().isoformat(),
    }

    index = _load_index()
    index.append(entry)
    _save_index(index)

    return {
        **entry,
        "success": True,
        "private_key": private_key_text,
        "system_saved": False,  # routers/ssh.py handles DB persistence
        "message": f"Private key saved in: {priv_path}",
    }

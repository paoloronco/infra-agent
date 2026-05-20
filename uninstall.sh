#!/bin/bash

# AI Agent - Complete Uninstaller
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
export TZ=Etc/UTC

INSTALL_DIR="/opt/ai-agent"
PURGE_DEPS="no"
AUTO_YES="no"

APP_PACKAGES=(nodejs nginx)
MANIFEST_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes) AUTO_YES="yes"; shift ;;
        --install-dir) INSTALL_DIR="$2"; shift 2 ;;
        --purge-deps) PURGE_DEPS="yes"; shift ;;
        --keep-deps) PURGE_DEPS="no"; shift ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

if [[ ! -t 0 && "$AUTO_YES" == "no" ]]; then
    AUTO_YES="yes"
fi

if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root/sudo"
   exit 1
fi

confirm() {
    local prompt="$1"
    if [[ "$AUTO_YES" == "yes" ]]; then
        return 0
    fi
    read -r -p "$prompt [y/N]: " answer
    [[ "$answer" == "y" || "$answer" == "Y" ]]
}

systemd_is_running() {
    command -v systemctl >/dev/null 2>&1 && systemctl list-units >/dev/null 2>&1
}

reload_nginx_if_running() {
    if ! command -v nginx >/dev/null 2>&1; then
        return
    fi
    nginx -t >/dev/null 2>&1 || return

    if systemd_is_running; then
        systemctl reload nginx 2>/dev/null || true
    elif command -v service >/dev/null 2>&1; then
        service nginx reload 2>/dev/null || service nginx restart 2>/dev/null || true
    else
        nginx -s reload 2>/dev/null || true
    fi
}

echo "--- AI Agent Uninstaller ---"
echo "Install directory: $INSTALL_DIR"

if ! confirm "Uninstall AI Agent and remove all app data"; then
    echo "Cancelled."
    exit 0
fi

MANIFEST_FILE="$INSTALL_DIR/.ai-agent-installed-packages"
PURGE_PACKAGES=()

if [[ "$PURGE_DEPS" == "no" && "$AUTO_YES" == "no" ]]; then
    if confirm "Also purge packages installed specifically for AI Agent"; then
        PURGE_DEPS="yes"
    fi
fi

if [[ "$PURGE_DEPS" == "yes" ]]; then
    if [[ -f "$MANIFEST_FILE" ]]; then
        while IFS= read -r package; do
            [[ -n "$package" ]] && PURGE_PACKAGES+=("$package")
        done < "$MANIFEST_FILE"
    else
        PURGE_PACKAGES=("${APP_PACKAGES[@]}")
    fi
fi

echo "Stopping service..."
if systemd_is_running; then
    systemctl stop ai-agent 2>/dev/null || true
    systemctl disable ai-agent 2>/dev/null || true
    systemctl reset-failed ai-agent 2>/dev/null || true
fi
if [[ -f /run/ai-agent.pid ]]; then
    pid="$(cat /run/ai-agent.pid 2>/dev/null || true)"
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
    rm -f /run/ai-agent.pid
fi
pkill -u ai-agent 2>/dev/null || true

echo "Removing systemd unit..."
rm -f /etc/systemd/system/ai-agent.service
if systemd_is_running; then
    systemctl daemon-reload
fi

echo "Removing Nginx config..."
rm -f /etc/nginx/sites-enabled/ai-agent
rm -f /etc/nginx/sites-available/ai-agent
reload_nginx_if_running

echo "Removing project files and runtime data..."
rm -rf "$INSTALL_DIR"
rm -rf /home/ai-agent/.npm /home/ai-agent/.cache /var/log/ai-agent

echo "Removing system user..."
userdel -r ai-agent 2>/dev/null || userdel ai-agent 2>/dev/null || true
rm -rf /home/ai-agent

if [[ "$PURGE_DEPS" == "yes" ]]; then
    echo "Purging AI Agent packages..."
    safe_packages=()
    for package in "${PURGE_PACKAGES[@]}"; do
        case "$package" in
            curl|ca-certificates|gnupg|git|iproute2|python3)
                echo "Keeping system package: $package"
                ;;
            *)
                safe_packages+=("$package")
                ;;
        esac
    done

    if [[ ${#safe_packages[@]} -gt 0 ]]; then
        apt-get remove --purge -y "${safe_packages[@]}" || true
    fi
    rm -f /etc/apt/sources.list.d/nodesource.list
    rm -f /etc/apt/keyrings/nodesource.gpg /usr/share/keyrings/nodesource.gpg
    apt-get autoremove --purge -y || true
    apt-get autoclean -y || true
fi

echo "Uninstallation complete."
if [[ "$PURGE_DEPS" != "yes" ]]; then
    echo "Packages were kept. Run with --purge-deps to remove app-owned packages too."
fi

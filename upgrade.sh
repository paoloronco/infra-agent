#!/usr/bin/env bash

# Infra Agent native Linux upgrader.
# It expects an install created by install.sh with a git checkout in INSTALL_DIR.

set -Eeuo pipefail
umask 027

INSTALL_DIR="$(dirname "$(readlink -f "$0")")"
SERVICE_NAME="ai-agent"
APP_USER="ai-agent"
APP_GROUP="ai-agent"
APP_HOME="/home/ai-agent"
BACKEND_PORT="8000"
LOCAL_CHANGES_BACKUP_DIR=""
PRESERVED_TRACKED_FILES=(
    "backend/agent_config.json"
    "backend/agent_memory.md"
)

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { printf "%b[INFO]%b %s\n" "$BLUE" "$NC" "$1"; }
warn() { printf "%b[WARN]%b %s\n" "$YELLOW" "$NC" "$1"; }
success() { printf "%b[OK]%b %s\n" "$GREEN" "$NC" "$1"; }
fatal() { printf "%b[ERROR]%b %s\n" "$RED" "$NC" "$1" >&2; exit 1; }

on_error() {
    printf "%b[ERROR]%b Upgrade stopped near line %s (exit code %s).\n" "$RED" "$NC" "$1" "$2" >&2
    exit "$2"
}
trap 'on_error "$LINENO" "$?"' ERR

systemd_is_running() {
    command -v systemctl >/dev/null 2>&1 \
        && [[ -d /run/systemd/system ]] \
        && systemctl list-unit-files >/dev/null 2>&1
}

run_as_app() {
    if command -v runuser >/dev/null 2>&1; then
        runuser -u "$APP_USER" -- env HOME="$APP_HOME" "$@"
        return
    fi

    if command -v sudo >/dev/null 2>&1; then
        sudo -H -u "$APP_USER" "$@"
        return
    fi

    fatal "runuser or sudo is required to execute commands as $APP_USER."
}

read_env_value() {
    local key="$1"
    local env_file="$INSTALL_DIR/backend/.env"
    if [[ -f "$env_file" ]]; then
        grep -E "^${key}=" "$env_file" | tail -n1 | cut -d= -f2- || true
    fi
}

resolve_backend_port() {
    local configured_port=""
    configured_port="$(read_env_value API_PORT)"
    if [[ "$configured_port" =~ ^[0-9]+$ ]]; then
        BACKEND_PORT="$configured_port"
    fi
}

backup_local_changes() {
    local status
    status="$(git status --porcelain --untracked-files=no)"
    [[ -n "$status" ]] || return 0

    local backup_dir="$INSTALL_DIR/backend/data/pre-upgrade-local-changes-$(date +%Y%m%d-%H%M%S)"
    LOCAL_CHANGES_BACKUP_DIR="$backup_dir"
    mkdir -p "$backup_dir"
    chown "$APP_USER:$APP_GROUP" "$backup_dir" 2>/dev/null || true

    git status --porcelain --untracked-files=no > "$backup_dir/status.txt"
    git diff > "$backup_dir/local-changes.patch" || true
    git diff --stat > "$backup_dir/local-changes.stat" || true

    local path
    for path in "${PRESERVED_TRACKED_FILES[@]}"; do
        if [[ -f "$INSTALL_DIR/$path" && -n "$(git status --porcelain -- "$path")" ]]; then
            mkdir -p "$backup_dir/$(dirname "$path")"
            cp -a "$INSTALL_DIR/$path" "$backup_dir/$path"
        fi
    done

    chown -R "$APP_USER:$APP_GROUP" "$backup_dir" 2>/dev/null || true
    warn "Tracked local changes detected. Saved diagnostics to $backup_dir."
    warn "Resetting tracked files so the upgrade can fast-forward cleanly."
    git reset --hard --quiet
}

restore_preserved_runtime_files() {
    local backup_dir="$1"
    [[ -n "$backup_dir" && -d "$backup_dir" ]] || return 0

    local path
    for path in "${PRESERVED_TRACKED_FILES[@]}"; do
        if [[ -f "$backup_dir/$path" ]]; then
            mkdir -p "$INSTALL_DIR/$(dirname "$path")"
            cp -a "$backup_dir/$path" "$INSTALL_DIR/$path"
            chown "$APP_USER:$APP_GROUP" "$INSTALL_DIR/$path" 2>/dev/null || true
        fi
    done
}

stop_background_backend() {
    if [[ -f /run/ai-agent.pid ]]; then
        local pid=""
        pid="$(cat /run/ai-agent.pid 2>/dev/null || true)"
        [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
        rm -f /run/ai-agent.pid
    fi
    pkill -f "$INSTALL_DIR/backend/main.py" 2>/dev/null || true
}

start_background_backend() {
    mkdir -p /var/log/ai-agent /run
    chown "$APP_USER:$APP_GROUP" /var/log/ai-agent
    rm -f /tmp/ai-agent.pid /run/ai-agent.pid
    run_as_app bash -c "cd '$INSTALL_DIR/backend' && nohup ./venv/bin/python main.py >/var/log/ai-agent/backend.log 2>&1 & echo \$! >/tmp/ai-agent.pid"
    mv /tmp/ai-agent.pid /run/ai-agent.pid
}

verify_backend() {
    local attempt
    for attempt in $(seq 1 20); do
        if curl -fsS "http://127.0.0.1:$BACKEND_PORT/health" >/dev/null 2>&1; then
            return
        fi
        sleep 1
    done

    if systemd_is_running; then
        journalctl -u "$SERVICE_NAME" -n 80 --no-pager 2>/dev/null || true
    elif [[ -f /var/log/ai-agent/backend.log ]]; then
        tail -n 80 /var/log/ai-agent/backend.log || true
    fi
    fatal "Backend health check failed on 127.0.0.1:$BACKEND_PORT."
}

refresh_nginx_config() {
    local nginx_conf="/etc/nginx/sites-available/${SERVICE_NAME}"
    local server_name="_"
    local nginx_host="_"

    if [[ ! -f "$nginx_conf" && -f "/etc/nginx/conf.d/${SERVICE_NAME}.conf" ]]; then
        nginx_conf="/etc/nginx/conf.d/${SERVICE_NAME}.conf"
    fi

    if ! command -v nginx >/dev/null 2>&1 || [[ ! -f "$nginx_conf" ]]; then
        warn "Nginx site config not found; skipping proxy refresh."
        return
    fi

    if [[ "$nginx_conf" == /etc/nginx/sites-available/* && -L /etc/nginx/sites-enabled/default ]]; then
        log "Disabling packaged Nginx welcome site so infra-agent owns port 80."
        rm -f /etc/nginx/sites-enabled/default
    fi

    server_name="$(grep -E '^[[:space:]]*server_name[[:space:]]+' "$nginx_conf" | head -n1 | sed -E 's/^[[:space:]]*server_name[[:space:]]+([^;]+);/\1/')"
    server_name="${server_name:-_}"
    nginx_host="${server_name%% *}"
    cp "$INSTALL_DIR/deploy/nginx.conf.template" "$nginx_conf"
    sed -i "s|/opt/ai-agent|$INSTALL_DIR|g" "$nginx_conf"
    sed -i "s|127.0.0.1:8000|127.0.0.1:$BACKEND_PORT|g" "$nginx_conf"
    sed -i "s|server_name _;|server_name $server_name;|g" "$nginx_conf"
    nginx -t

    if systemd_is_running; then
        systemctl reload nginx
    elif command -v service >/dev/null 2>&1 \
        && { service nginx reload 2>/dev/null || service nginx restart 2>/dev/null; }; then
        :
    else
        nginx -s reload 2>/dev/null || nginx
    fi

    if ! curl -fsS -H "Host: $nginx_host" "http://127.0.0.1/" >/dev/null 2>&1; then
        tail -n 80 /var/log/nginx/error.log 2>/dev/null || true
        fatal "Nginx did not serve the infra-agent frontend successfully on port 80."
    fi
}

[[ $EUID -eq 0 ]] || fatal "Run as root: sudo bash $0"
[[ -d "$INSTALL_DIR/.git" ]] || fatal "$INSTALL_DIR is not a git checkout. Re-run install.sh."
[[ -x "$INSTALL_DIR/backend/venv/bin/python" ]] || fatal "Backend virtualenv is missing. Re-run install.sh."
[[ -d "$INSTALL_DIR/frontend" ]] || fatal "Frontend directory is missing. Re-run install.sh."
id "$APP_USER" >/dev/null 2>&1 || fatal "Service account $APP_USER is missing. Re-run install.sh."

cd "$INSTALL_DIR"
resolve_backend_port

backup_local_changes

if [[ -f "$INSTALL_DIR/backend/data/app.db" ]]; then
    DB_BACKUP="$INSTALL_DIR/backend/data/app.db.pre-upgrade-$(date +%Y%m%d-%H%M%S)"
    cp -a "$INSTALL_DIR/backend/data/app.db" "$DB_BACKUP"
    chown "$APP_USER:$APP_GROUP" "$DB_BACKUP" 2>/dev/null || true
    success "SQLite snapshot created: $DB_BACKUP"
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[[ "$BRANCH" != "HEAD" ]] || fatal "Detached HEAD upgrades are not automatic. Re-run install.sh --ref <tag-or-branch>."
OLD_COMMIT="$(git rev-parse --short HEAD)"
log "Fetching updates for $BRANCH from origin..."
git fetch --quiet origin "$BRANCH"
git merge --ff-only "origin/$BRANCH"
NEW_COMMIT="$(git rev-parse --short HEAD)"
log "Revision: $OLD_COMMIT -> $NEW_COMMIT"
restore_preserved_runtime_files "$LOCAL_CHANGES_BACKUP_DIR"

mkdir -p "$APP_HOME/.cache/pip" "$APP_HOME/.npm"
chown -R "$APP_USER:$APP_GROUP" "$APP_HOME/.cache" "$APP_HOME/.npm"

log "Updating backend Python dependencies..."
run_as_app "$INSTALL_DIR/backend/venv/bin/python" -m pip install --quiet --upgrade pip setuptools wheel
run_as_app "$INSTALL_DIR/backend/venv/bin/python" -m pip install --quiet --upgrade -r "$INSTALL_DIR/backend/requirements.txt"

NODE_BINARY="$(find "$INSTALL_DIR/.runtime" -type f -path '*/bin/node' -print -quit 2>/dev/null || true)"
if [[ -n "$NODE_BINARY" ]]; then
    NODE_PATH="$(dirname "$NODE_BINARY"):/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
elif command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    NODE_PATH="$PATH"
else
    fatal "Node build runtime is missing. Re-run install.sh to restore .runtime."
fi

log "Rebuilding frontend from package-lock.json..."
run_as_app env PATH="$NODE_PATH" npm --prefix "$INSTALL_DIR/frontend" ci --no-audit --no-fund --silent
run_as_app env PATH="$NODE_PATH" npm --prefix "$INSTALL_DIR/frontend" run build --silent
rm -rf "$INSTALL_DIR/frontend/node_modules"

# Nginx workers are not the service user. Expose only the SPA build path.
chmod 755 "$INSTALL_DIR" "$INSTALL_DIR/frontend" "$INSTALL_DIR/frontend/dist"
find "$INSTALL_DIR/frontend/dist" -type d -exec chmod 755 {} +
find "$INSTALL_DIR/frontend/dist" -type f -exec chmod 644 {} +

if systemd_is_running && [[ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]]; then
    log "Refreshing systemd unit and restarting service..."
    cp "$INSTALL_DIR/deploy/ai-agent.service" "/etc/systemd/system/${SERVICE_NAME}.service"
    sed -i "s|/opt/ai-agent|$INSTALL_DIR|g" "/etc/systemd/system/${SERVICE_NAME}.service"
    systemctl daemon-reload
    systemctl restart "$SERVICE_NAME"
else
    warn "systemd service not detected; restarting background backend."
    stop_background_backend
    start_background_backend
fi

verify_backend
refresh_nginx_config
success "Upgrade completed at revision $NEW_COMMIT."

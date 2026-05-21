#!/usr/bin/env bash

# Infra Agent native Linux installer.
# Supported package-manager families: apt, dnf/yum, pacman.
# Alpine and other musl-only targets should use a container image or a dedicated package.

set -Eeuo pipefail
umask 027

APP_NAME="infra-agent"
SERVICE_NAME="ai-agent"
APP_USER="ai-agent"
APP_GROUP="ai-agent"
APP_HOME="/home/ai-agent"
REPO_URL="${INFRA_AGENT_REPO_URL:-https://github.com/paoloronco/infra-agent.git}"
SOURCE_REF="${INFRA_AGENT_REF:-master}"
NODE_VERSION="${INFRA_AGENT_NODE_VERSION:-24.15.0}"

if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
    SCRIPT_DIR="$(pwd)"
fi

PROJECT_SOURCE="$SCRIPT_DIR"
INSTALL_DIR="/opt/ai-agent"
BACKEND_PORT="8000"
BACKEND_PORT_EXPLICIT="no"
DOMAIN="_"
DOMAIN_EXPLICIT="no"
INSTALL_NGINX="yes"
RUNTIME_MODE="auto"
AUTO_YES="no"

PACKAGE_MANAGER=""
OS_ID="unknown"
PYTHON_BIN=""
NODE_ARCH=""
NODE_HOME=""
STAGE_DIR=""
TMP_DIR=""
BACKUP_DIR=""
LOCK_DIR=""
CUTOVER_DONE="no"
PACKAGE_MANIFEST="$(mktemp)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { printf "%b[INFO]%b %s\n" "$BLUE" "$NC" "$1"; }
warn() { printf "%b[WARN]%b %s\n" "$YELLOW" "$NC" "$1"; }
success() { printf "%b[OK]%b %s\n" "$GREEN" "$NC" "$1"; }
fatal() { printf "%b[ERROR]%b %s\n" "$RED" "$NC" "$1" >&2; exit 1; }

usage() {
    cat <<'USAGE'
Usage: sudo bash install.sh [options]

Options:
  --yes                    Accept defaults for non-interactive installs.
  --install-dir PATH       Absolute install directory. Default: /opt/ai-agent
  --backend-port PORT      Backend port. Default: first free port from 8000.
  --domain NAME            Nginx server_name or IP. Default: detected host IP.
  --no-nginx               Install backend without the Nginx reverse proxy.
  --runtime MODE           auto, systemd, or background. Default: auto.
  --no-systemd             Alias for --runtime background.
  --ref REF                Git branch/tag/commit to install. Default: master.
  --repo-url URL           Git source URL. Default: upstream GitHub repository.
  --help                   Show this help.

Environment overrides:
  INFRA_AGENT_REF, INFRA_AGENT_REPO_URL, INFRA_AGENT_NODE_VERSION
USAGE
}

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

    fatal "runuser or sudo is required to execute commands as $APP_USER"
}

cleanup() {
    if [[ -n "${STAGE_DIR:-}" && -d "$STAGE_DIR" ]]; then
        rm -rf "$STAGE_DIR"
    fi
    if [[ -n "${TMP_DIR:-}" && -d "$TMP_DIR" ]]; then
        rm -rf "$TMP_DIR"
    fi
    if [[ -n "${LOCK_DIR:-}" && -d "$LOCK_DIR" ]]; then
        rmdir "$LOCK_DIR" 2>/dev/null || true
    fi
    rm -f "$PACKAGE_MANIFEST"
}

restart_existing_runtime_best_effort() {
    if systemd_is_running && [[ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]]; then
        systemctl daemon-reload >/dev/null 2>&1 || true
        systemctl restart "$SERVICE_NAME" >/dev/null 2>&1 || true
        return
    fi

    if [[ -x "$INSTALL_DIR/backend/venv/bin/python" ]]; then
        mkdir -p /var/log/ai-agent /run
        chown "$APP_USER:$APP_GROUP" /var/log/ai-agent 2>/dev/null || true
        run_as_app bash -c "cd '$INSTALL_DIR/backend' && nohup ./venv/bin/python main.py >/var/log/ai-agent/backend.log 2>&1 & echo \$! >/tmp/ai-agent.pid" || true
        if [[ -f /tmp/ai-agent.pid ]]; then
            mv /tmp/ai-agent.pid /run/ai-agent.pid 2>/dev/null || true
        fi
    fi
}

rollback_after_failure() {
    if [[ "$CUTOVER_DONE" != "yes" || -z "${BACKUP_DIR:-}" || ! -d "$BACKUP_DIR" ]]; then
        return
    fi

    warn "Install failed after cutover; restoring the previous install tree."
    stop_previous_app || true
    rm -rf "$INSTALL_DIR"
    mv "$BACKUP_DIR" "$INSTALL_DIR"
    BACKUP_DIR=""
    restart_existing_runtime_best_effort
}

on_error() {
    local line="$1"
    local code="$2"
    rollback_after_failure
    printf "%b[ERROR]%b Installer stopped near line %s (exit code %s).\n" "$RED" "$NC" "$line" "$code" >&2
    exit "$code"
}

trap cleanup EXIT
trap 'on_error "$LINENO" "$?"' ERR

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes)
            AUTO_YES="yes"
            shift
            ;;
        --install-dir)
            INSTALL_DIR="${2:-}"
            shift 2
            ;;
        --backend-port)
            BACKEND_PORT="${2:-}"
            BACKEND_PORT_EXPLICIT="yes"
            shift 2
            ;;
        --domain)
            DOMAIN="${2:-}"
            DOMAIN_EXPLICIT="yes"
            shift 2
            ;;
        --no-nginx)
            INSTALL_NGINX="no"
            shift
            ;;
        --runtime)
            RUNTIME_MODE="${2:-}"
            shift 2
            ;;
        --no-systemd)
            RUNTIME_MODE="background"
            shift
            ;;
        --ref)
            SOURCE_REF="${2:-}"
            shift 2
            ;;
        --repo-url)
            REPO_URL="${2:-}"
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            fatal "Unknown argument: $1"
            ;;
    esac
done

if [[ ! -t 0 && "$AUTO_YES" == "no" ]]; then
    AUTO_YES="yes"
fi

[[ $EUID -eq 0 ]] || fatal "Run the installer as root, for example via sudo."

validate_install_dir() {
    [[ -n "$INSTALL_DIR" ]] || fatal "Install directory cannot be empty."
    [[ "$INSTALL_DIR" == /* ]] || fatal "Install directory must be an absolute Linux path."
    [[ "$INSTALL_DIR" != "/" ]] || fatal "Refusing to install into /."
    [[ "$INSTALL_DIR" != "/opt" ]] || fatal "Refusing to replace /opt."
    [[ "$INSTALL_DIR" != *[[:space:]]* ]] || fatal "Install directory cannot contain whitespace."
}

validate_port() {
    [[ "$BACKEND_PORT" =~ ^[0-9]+$ ]] || fatal "Invalid backend port: $BACKEND_PORT"
    (( BACKEND_PORT >= 1 && BACKEND_PORT <= 65535 )) || fatal "Backend port must be between 1 and 65535."
}

validate_domain() {
    [[ -n "$DOMAIN" ]] || fatal "Domain cannot be empty."
    [[ "$DOMAIN" =~ ^[_A-Za-z0-9.*:-]+$ ]] \
        || fatal "Domain/server_name contains unsupported characters: $DOMAIN"
}

acquire_lock() {
    mkdir -p /run/lock 2>/dev/null || true
    LOCK_DIR="/run/lock/${APP_NAME}.install.lock"
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
        LOCK_DIR="/tmp/${APP_NAME}.install.lock"
        mkdir "$LOCK_DIR" 2>/dev/null || fatal "Another infra-agent install appears to be running."
    fi
}

detect_package_manager() {
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        OS_ID="${ID:-unknown}"
    fi

    if command -v apt-get >/dev/null 2>&1; then
        PACKAGE_MANAGER="apt"
    elif command -v dnf >/dev/null 2>&1; then
        PACKAGE_MANAGER="dnf"
    elif command -v yum >/dev/null 2>&1; then
        PACKAGE_MANAGER="yum"
    elif command -v pacman >/dev/null 2>&1; then
        PACKAGE_MANAGER="pacman"
    elif command -v apk >/dev/null 2>&1; then
        fatal "Alpine/musl native installs are not supported by this installer yet."
    else
        fatal "Unsupported Linux environment: apt, dnf/yum, or pacman is required."
    fi
}

package_is_installed() {
    local package="$1"
    case "$PACKAGE_MANAGER" in
        apt)
            dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q "install ok installed"
            ;;
        dnf|yum)
            rpm -q "$package" >/dev/null 2>&1
            ;;
        pacman)
            pacman -Q "$package" >/dev/null 2>&1
            ;;
    esac
}

remember_if_missing() {
    local package="$1"
    if ! package_is_installed "$package"; then
        printf "%s\n" "$package" >> "$PACKAGE_MANIFEST"
    fi
}

install_system_dependencies() {
    local packages=()

    log "Installing system dependencies with $PACKAGE_MANAGER..."
    case "$PACKAGE_MANAGER" in
        apt)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update
            packages=(
                ca-certificates curl git iproute2 procps tar xz-utils
                python3 python3-pip python3-venv python3-dev
                build-essential libffi-dev libssl-dev
            )
            [[ "$INSTALL_NGINX" == "yes" ]] && packages+=(nginx)
            ;;
        dnf|yum)
            packages=(
                ca-certificates curl git iproute procps-ng tar xz
                python3 python3-pip python3-devel
                gcc gcc-c++ make libffi-devel openssl-devel shadow-utils
            )
            [[ "$INSTALL_NGINX" == "yes" ]] && packages+=(nginx)
            ;;
        pacman)
            packages=(
                ca-certificates curl git iproute2 procps-ng tar xz
                python python-pip base-devel
            )
            [[ "$INSTALL_NGINX" == "yes" ]] && packages+=(nginx)
            pacman -Sy --noconfirm
            ;;
    esac

    local package
    for package in "${packages[@]}"; do
        remember_if_missing "$package"
    done

    case "$PACKAGE_MANAGER" in
        apt)
            apt-get install -y "${packages[@]}"
            ;;
        dnf)
            dnf install -y "${packages[@]}"
            ;;
        yum)
            yum install -y "${packages[@]}"
            ;;
        pacman)
            pacman -S --needed --noconfirm "${packages[@]}"
            ;;
    esac
}

python_is_supported() {
    "$1" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
}

resolve_python() {
    local candidate
    for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && python_is_supported "$candidate"; then
            PYTHON_BIN="$(command -v "$candidate")"
            log "Using Python $("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')."
            return
        fi
    done

    fatal "Python 3.10+ is required. Upgrade the base OS Python or install a supported Python before retrying."
}

detect_local_ip() {
    local ip=""
    ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}')"
    [[ -n "$ip" ]] && printf "%s\n" "$ip" && return

    ip="$(ip -4 addr show 2>/dev/null | awk '/inet / && !/127\./ {gsub("/.*","",$2); print $2; exit}')"
    [[ -n "$ip" ]] && printf "%s\n" "$ip" && return

    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    [[ -n "$ip" ]] && printf "%s\n" "$ip" && return

    printf "_\n"
}

port_is_free() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        ! ss -H -ltn "( sport = :$port )" 2>/dev/null | grep -q .
        return
    fi
    if command -v lsof >/dev/null 2>&1; then
        ! lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
        return
    fi
    return 0
}

describe_port_owner() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        ss -ltnp "( sport = :$port )" 2>/dev/null || true
        return
    fi
    if command -v lsof >/dev/null 2>&1; then
        lsof -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
    fi
}

resolve_backend_port() {
    if port_is_free "$BACKEND_PORT"; then
        return
    fi

    if [[ "$BACKEND_PORT_EXPLICIT" == "yes" ]]; then
        describe_port_owner "$BACKEND_PORT"
        fatal "Backend port $BACKEND_PORT is already in use."
    fi

    local candidate
    for candidate in $(seq "$((BACKEND_PORT + 1))" 8099); do
        if port_is_free "$candidate"; then
            warn "Backend port $BACKEND_PORT is busy; using $candidate."
            BACKEND_PORT="$candidate"
            return
        fi
    done

    describe_port_owner "$BACKEND_PORT"
    fatal "No free backend port found in range $BACKEND_PORT-8099."
}

stop_previous_app() {
    if systemd_is_running; then
        if systemctl list-unit-files "${SERVICE_NAME}.service" 2>/dev/null | grep -q "^${SERVICE_NAME}.service" \
            || [[ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]]; then
            log "Stopping previous $SERVICE_NAME service..."
            systemctl stop "$SERVICE_NAME" 2>/dev/null || true
            systemctl reset-failed "$SERVICE_NAME" 2>/dev/null || true
        fi
    fi

    if [[ -f /run/ai-agent.pid ]]; then
        local pid
        pid="$(cat /run/ai-agent.pid 2>/dev/null || true)"
        [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
        rm -f /run/ai-agent.pid
    fi

    pkill -f "$INSTALL_DIR/backend/main.py" 2>/dev/null || true
}

ensure_app_user() {
    local nologin_shell="/usr/sbin/nologin"
    [[ -x "$nologin_shell" ]] || nologin_shell="/bin/false"

    if ! getent group "$APP_GROUP" >/dev/null 2>&1; then
        groupadd --system "$APP_GROUP" 2>/dev/null || groupadd "$APP_GROUP"
    fi

    if ! id "$APP_USER" >/dev/null 2>&1; then
        log "Creating service account $APP_USER..."
        useradd --system --create-home --home-dir "$APP_HOME" --gid "$APP_GROUP" --shell "$nologin_shell" "$APP_USER" \
            2>/dev/null || useradd -m -d "$APP_HOME" -g "$APP_GROUP" -s "$nologin_shell" "$APP_USER"
    fi

    mkdir -p "$APP_HOME"
    chown "$APP_USER:$APP_GROUP" "$APP_HOME"
}

prepare_stage_dir() {
    local install_parent
    install_parent="$(dirname "$INSTALL_DIR")"
    mkdir -p "$install_parent"
    STAGE_DIR="$(mktemp -d "$install_parent/.${APP_NAME}.stage.XXXXXX")"
    TMP_DIR="$(mktemp -d)"
}

stage_source() {
    if [[ -d "$PROJECT_SOURCE/backend" && -d "$PROJECT_SOURCE/frontend" ]]; then
        log "Staging source from local checkout $PROJECT_SOURCE..."
        cp -a "$PROJECT_SOURCE/." "$STAGE_DIR/"
    else
        log "Cloning $REPO_URL at ref $SOURCE_REF..."
        if ! git clone --quiet --depth 1 --branch "$SOURCE_REF" "$REPO_URL" "$STAGE_DIR"; then
            rm -rf "$STAGE_DIR"
            STAGE_DIR="$(mktemp -d "$(dirname "$INSTALL_DIR")/.${APP_NAME}.stage.XXXXXX")"
            git clone --quiet "$REPO_URL" "$STAGE_DIR"
            git -C "$STAGE_DIR" checkout --quiet "$SOURCE_REF"
        fi
    fi

    [[ -f "$STAGE_DIR/backend/requirements.txt" ]] || fatal "Staged source is missing backend/requirements.txt."
    [[ -f "$STAGE_DIR/frontend/package-lock.json" ]] || fatal "Staged source is missing frontend/package-lock.json."
    rm -rf "$STAGE_DIR/backend/venv" "$STAGE_DIR/frontend/node_modules" "$STAGE_DIR/frontend/dist" "$STAGE_DIR/.runtime"
}

sha256_file() {
    local file="$1"
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$file" | awk '{print $1}'
        return
    fi
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$file" | awk '{print $1}'
        return
    fi
    openssl dgst -sha256 "$file" | awk '{print $NF}'
}

download_file() {
    local url="$1"
    local output="$2"
    curl --fail --silent --show-error --location \
        --retry 4 --retry-delay 2 --connect-timeout 20 \
        "$url" -o "$output"
}

resolve_node_arch() {
    case "$(uname -m)" in
        x86_64|amd64)
            NODE_ARCH="x64"
            ;;
        aarch64|arm64)
            NODE_ARCH="arm64"
            ;;
        *)
            fatal "Unsupported CPU architecture for the bundled Node build: $(uname -m)"
            ;;
    esac
}

install_build_node_runtime() {
    resolve_node_arch
    local archive="node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz"
    local dist_url="https://nodejs.org/dist/v${NODE_VERSION}"
    local sums="$TMP_DIR/SHASUMS256.txt"
    local archive_path="$TMP_DIR/$archive"
    local expected=""
    local actual=""

    log "Downloading verified Node.js v$NODE_VERSION build runtime for the frontend..."
    download_file "$dist_url/SHASUMS256.txt" "$sums"
    download_file "$dist_url/$archive" "$archive_path"

    expected="$(awk -v archive="$archive" '$2 == archive {print $1}' "$sums")"
    [[ -n "$expected" ]] || fatal "Could not find a checksum for $archive."
    actual="$(sha256_file "$archive_path")"
    [[ "$actual" == "$expected" ]] || fatal "Checksum verification failed for $archive."

    mkdir -p "$STAGE_DIR/.runtime"
    tar -xJf "$archive_path" -C "$STAGE_DIR/.runtime"
    NODE_HOME="$STAGE_DIR/.runtime/node-v${NODE_VERSION}-linux-${NODE_ARCH}"
    [[ -x "$NODE_HOME/bin/node" ]] || fatal "Bundled Node runtime extraction failed."
}

prepare_backend_and_frontend() {
    local node_path="$NODE_HOME/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

    chown -R "$APP_USER:$APP_GROUP" "$STAGE_DIR"
    mkdir -p "$APP_HOME/.cache/pip" "$APP_HOME/.npm"
    chown -R "$APP_USER:$APP_GROUP" "$APP_HOME/.cache" "$APP_HOME/.npm"

    log "Creating backend virtual environment..."
    run_as_app "$PYTHON_BIN" -m venv "$STAGE_DIR/backend/venv"
    run_as_app "$STAGE_DIR/backend/venv/bin/python" -m pip install --upgrade pip setuptools wheel
    run_as_app "$STAGE_DIR/backend/venv/bin/python" -m pip install --no-cache-dir -r "$STAGE_DIR/backend/requirements.txt"

    log "Building frontend from lockfile..."
    run_as_app env PATH="$node_path" npm --prefix "$STAGE_DIR/frontend" ci --no-audit --no-fund
    run_as_app env PATH="$node_path" npm --prefix "$STAGE_DIR/frontend" run build --silent
    rm -rf "$STAGE_DIR/frontend/node_modules"
}

merge_package_manifest() {
    local old_manifest="$INSTALL_DIR/.ai-agent-installed-packages"
    if [[ -f "$old_manifest" ]]; then
        while IFS= read -r package; do
            [[ -n "$package" ]] && printf "%s\n" "$package" >> "$PACKAGE_MANIFEST"
        done < "$old_manifest"
    fi

    sort -u "$PACKAGE_MANIFEST" > "$STAGE_DIR/.ai-agent-installed-packages"
    printf "%s\n" "$PACKAGE_MANAGER" > "$STAGE_DIR/.ai-agent-package-manager"
}

preserve_runtime_state() {
    if [[ -d "$INSTALL_DIR/backend/data" ]]; then
        log "Preserving backend data directory..."
        rm -rf "$STAGE_DIR/backend/data"
        cp -a "$INSTALL_DIR/backend/data" "$STAGE_DIR/backend/data"
    fi

    if [[ -f "$INSTALL_DIR/backend/.env" ]]; then
        log "Preserving backend environment file..."
        cp -a "$INSTALL_DIR/backend/.env" "$STAGE_DIR/backend/.env"
    elif [[ ! -f "$STAGE_DIR/backend/.env" ]]; then
        cp "$STAGE_DIR/backend/.env.example" "$STAGE_DIR/backend/.env"
    fi

    # Move runtime files created by older installs under the durable data root.
    if [[ -d "$INSTALL_DIR/backend/uploads" && ! -e "$STAGE_DIR/backend/data/uploads" ]]; then
        log "Migrating legacy backend uploads into backend/data..."
        mkdir -p "$STAGE_DIR/backend/data"
        cp -a "$INSTALL_DIR/backend/uploads" "$STAGE_DIR/backend/data/uploads"
    fi
    if [[ -d "$INSTALL_DIR/backend/logs" && ! -e "$STAGE_DIR/backend/data/logs" ]]; then
        log "Migrating legacy backend file logs into backend/data..."
        mkdir -p "$STAGE_DIR/backend/data"
        cp -a "$INSTALL_DIR/backend/logs" "$STAGE_DIR/backend/data/logs"
    fi
}

set_env_value() {
    local env_file="$1"
    local key="$2"
    local value="$3"

    if grep -q "^${key}=" "$env_file"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$env_file"
    else
        printf "%s=%s\n" "$key" "$value" >> "$env_file"
    fi
}

configure_env_file() {
    local bind_host="0.0.0.0"
    [[ "$INSTALL_NGINX" == "yes" ]] && bind_host="127.0.0.1"

    set_env_value "$STAGE_DIR/backend/.env" "API_HOST" "$bind_host"
    set_env_value "$STAGE_DIR/backend/.env" "API_PORT" "$BACKEND_PORT"
    set_env_value "$STAGE_DIR/backend/.env" "AUTH_ENABLED_BY_DEFAULT" "true"
    chmod 600 "$STAGE_DIR/backend/.env"
}

prepare_permissions() {
    mkdir -p "$STAGE_DIR/backend/data"
    chmod 750 "$STAGE_DIR/backend/data"
    chmod +x "$STAGE_DIR"/*.sh 2>/dev/null || true
    chown -R "$APP_USER:$APP_GROUP" "$STAGE_DIR"

    # Nginx workers are not the service user. Expose only the SPA build path.
    chmod 755 "$STAGE_DIR" "$STAGE_DIR/frontend" "$STAGE_DIR/frontend/dist"
    find "$STAGE_DIR/frontend/dist" -type d -exec chmod 755 {} +
    find "$STAGE_DIR/frontend/dist" -type f -exec chmod 644 {} +
}

swap_install_tree() {
    if [[ -d "$INSTALL_DIR" ]]; then
        BACKUP_DIR="$(mktemp -d "$(dirname "$INSTALL_DIR")/.${APP_NAME}.rollback.XXXXXX")"
        rmdir "$BACKUP_DIR"
        mv "$INSTALL_DIR" "$BACKUP_DIR"
    fi

    mv "$STAGE_DIR" "$INSTALL_DIR"
    STAGE_DIR=""
    CUTOVER_DONE="yes"
}

resolve_runtime_mode() {
    case "$RUNTIME_MODE" in
        auto)
            if systemd_is_running; then
                RUNTIME_MODE="systemd"
            else
                RUNTIME_MODE="background"
                warn "systemd is not running; using background mode. Use a service manager or container runtime for production."
            fi
            ;;
        systemd)
            systemd_is_running || fatal "systemd runtime requested but systemd is not running."
            ;;
        background)
            ;;
        *)
            fatal "Unsupported runtime mode: $RUNTIME_MODE"
            ;;
    esac
}

install_systemd_service() {
    local service_file="/etc/systemd/system/${SERVICE_NAME}.service"
    log "Configuring systemd service..."
    cp "$INSTALL_DIR/deploy/ai-agent.service" "$service_file"
    sed -i "s|/opt/ai-agent|$INSTALL_DIR|g" "$service_file"
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    systemctl restart "$SERVICE_NAME"
}

start_backend_background() {
    log "Starting backend in background mode..."
    mkdir -p /var/log/ai-agent /run
    chown "$APP_USER:$APP_GROUP" /var/log/ai-agent
    rm -f /run/ai-agent.pid /tmp/ai-agent.pid
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

    if [[ "$RUNTIME_MODE" == "systemd" ]]; then
        journalctl -u "$SERVICE_NAME" -n 80 --no-pager 2>/dev/null || true
    elif [[ -f /var/log/ai-agent/backend.log ]]; then
        tail -n 80 /var/log/ai-agent/backend.log || true
    fi
    fatal "Backend health check failed on 127.0.0.1:$BACKEND_PORT."
}

restart_nginx() {
    nginx -t
    if systemd_is_running; then
        systemctl enable nginx >/dev/null 2>&1 || true
        systemctl restart nginx
    elif command -v service >/dev/null 2>&1; then
        service nginx restart || service nginx start
    else
        nginx -s reload 2>/dev/null || nginx
    fi
}

verify_nginx_frontend() {
    local attempt
    for attempt in $(seq 1 10); do
        if curl -fsS -H "Host: $DOMAIN" "http://127.0.0.1/" >/dev/null 2>&1; then
            return
        fi
        sleep 1
    done

    tail -n 80 /var/log/nginx/error.log 2>/dev/null || true
    fatal "Nginx did not serve the infra-agent frontend successfully on port 80."
}

configure_nginx() {
    local nginx_conf=""
    log "Configuring Nginx reverse proxy..."

    if [[ -d /etc/nginx/sites-available && -d /etc/nginx/sites-enabled ]]; then
        nginx_conf="/etc/nginx/sites-available/${SERVICE_NAME}"
        cp "$INSTALL_DIR/deploy/nginx.conf.template" "$nginx_conf"
        ln -sf "$nginx_conf" "/etc/nginx/sites-enabled/${SERVICE_NAME}"
        if [[ -L /etc/nginx/sites-enabled/default ]]; then
            log "Disabling packaged Nginx welcome site so infra-agent owns port 80."
            rm -f /etc/nginx/sites-enabled/default
        fi
    elif [[ -d /etc/nginx/conf.d ]]; then
        nginx_conf="/etc/nginx/conf.d/${SERVICE_NAME}.conf"
        cp "$INSTALL_DIR/deploy/nginx.conf.template" "$nginx_conf"
    else
        fatal "Nginx config layout is not recognized. Retry with --no-nginx or configure the proxy manually."
    fi

    sed -i "s|/opt/ai-agent|$INSTALL_DIR|g" "$nginx_conf"
    sed -i "s|127.0.0.1:8000|127.0.0.1:$BACKEND_PORT|g" "$nginx_conf"
    sed -i "s|server_name _;|server_name $DOMAIN;|g" "$nginx_conf"
    restart_nginx
    verify_nginx_frontend
}

print_summary() {
    local public_host="$DOMAIN"
    [[ "$public_host" == "_" ]] && public_host="$(detect_local_ip)"

    success "Infra Agent installation completed."
    if [[ "$INSTALL_NGINX" == "yes" ]]; then
        printf "\nAccess URL: http://%s\n" "$public_host"
    else
        printf "\nAccess URL: http://%s:%s\n" "$(detect_local_ip)" "$BACKEND_PORT"
    fi
    printf "Install dir: %s\n" "$INSTALL_DIR"
    printf "Backend port: %s\n" "$BACKEND_PORT"
    printf "Runtime: %s\n" "$RUNTIME_MODE"
    printf "Source ref: %s\n" "$SOURCE_REF"
    printf "First-login bootstrap password: %s/backend/data/bootstrap_admin_password.txt\n" "$INSTALL_DIR"

    printf "\nUseful commands:\n"
    if [[ "$RUNTIME_MODE" == "systemd" ]]; then
        printf "  Logs:    sudo journalctl -u %s -f\n" "$SERVICE_NAME"
        printf "  Restart: sudo systemctl restart %s\n" "$SERVICE_NAME"
    else
        printf "  Logs:    sudo tail -f /var/log/ai-agent/backend.log\n"
        printf "  Restart: sudo bash %s/install.sh --yes --runtime background --backend-port %s\n" "$INSTALL_DIR" "$BACKEND_PORT"
    fi
    printf "  Upgrade: sudo bash %s/upgrade.sh\n" "$INSTALL_DIR"
    printf "  Remove:  sudo bash %s/uninstall.sh --yes\n" "$INSTALL_DIR"
}

validate_install_dir
validate_port
acquire_lock
detect_package_manager

DETECTED_IP="$(detect_local_ip)"
if [[ "$AUTO_YES" == "yes" && "$DOMAIN_EXPLICIT" == "no" ]]; then
    DOMAIN="$DETECTED_IP"
fi

if [[ "$AUTO_YES" == "no" ]]; then
    printf "%b--- Infra Agent Native Linux Setup ---%b\n" "$BLUE" "$NC"
    read -r -p "Install path [$INSTALL_DIR]: " input_dir
    INSTALL_DIR="${input_dir:-$INSTALL_DIR}"

    read -r -p "Backend port [$BACKEND_PORT]: " input_port
    BACKEND_PORT="${input_port:-$BACKEND_PORT}"
    [[ -n "$input_port" ]] && BACKEND_PORT_EXPLICIT="yes"

    read -r -p "Configure Nginx reverse proxy? (y/n) [y]: " input_nginx
    [[ "$input_nginx" == "n" || "$input_nginx" == "N" ]] && INSTALL_NGINX="no"

    if [[ "$INSTALL_NGINX" == "yes" ]]; then
        read -r -p "Domain or server IP [$DETECTED_IP]: " input_domain
        DOMAIN="${input_domain:-$DETECTED_IP}"
    fi
fi

validate_install_dir
validate_port
[[ "$DOMAIN" == "_" ]] || validate_domain

log "Detected OS id: $OS_ID; package manager: $PACKAGE_MANAGER."
install_system_dependencies
resolve_python
ensure_app_user
prepare_stage_dir
stage_source
install_build_node_runtime
prepare_backend_and_frontend

stop_previous_app
resolve_backend_port
preserve_runtime_state
configure_env_file
merge_package_manifest
prepare_permissions
swap_install_tree
resolve_runtime_mode

if [[ "$RUNTIME_MODE" == "systemd" ]]; then
    install_systemd_service
else
    start_backend_background
fi

verify_backend
if [[ "$INSTALL_NGINX" == "yes" ]]; then
    configure_nginx
fi

if [[ -n "${BACKUP_DIR:-}" && -d "$BACKUP_DIR" ]]; then
    rm -rf "$BACKUP_DIR"
    BACKUP_DIR=""
fi

print_summary

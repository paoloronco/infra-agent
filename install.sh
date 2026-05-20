#!/bin/bash

# AI Agent SSH & Troubleshooting - Production Installer
# Compatible with Ubuntu/Debian

set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
export TZ=Etc/UTC

if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
    SCRIPT_DIR="$(pwd)"
fi
REPO_URL="https://github.com/paoloronco/infra-agent.git"
PROJECT_SOURCE="$SCRIPT_DIR"
TMP_SOURCE=""
PACKAGE_MANIFEST="$(mktemp)"

# --- Configuration ---
INSTALL_DIR="/opt/ai-agent"
BACKEND_PORT="8000"
ENABLE_SYSTEMD="yes"
INSTALL_NGINX="yes"
DOMAIN="_"
AUTO_YES="no"
BACKEND_PORT_EXPLICIT="no"

# Colors for output
RED='\033[0,31m'
GREEN='\033[0,32m'
BLUE='\033[0,34m'
NC='\033[0m' # No Color

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

cleanup() {
    if [[ -n "$TMP_SOURCE" && -d "$TMP_SOURCE" ]]; then
        rm -rf "$TMP_SOURCE"
    fi
    rm -f "$PACKAGE_MANIFEST"
}
trap cleanup EXIT

package_is_installed() {
    dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q "install ok installed"
}

remember_if_missing() {
    local package="$1"
    if ! package_is_installed "$package"; then
        echo "$package" >> "$PACKAGE_MANIFEST"
    fi
}

systemd_is_running() {
    command -v systemctl >/dev/null 2>&1 && systemctl list-units >/dev/null 2>&1
}

run_as_ai_agent() {
    if command -v runuser >/dev/null 2>&1; then
        runuser -u ai-agent -- env HOME=/home/ai-agent "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo -H -u ai-agent "$@"
    else
        error "Neither runuser nor sudo is available to run commands as ai-agent"
    fi
}

stop_previous_app() {
    if systemd_is_running; then
        if systemctl list-unit-files ai-agent.service >/dev/null 2>&1 || [[ -f /etc/systemd/system/ai-agent.service ]]; then
            log "Stopping previous ai-agent service..."
            systemctl stop ai-agent 2>/dev/null || true
            systemctl reset-failed ai-agent 2>/dev/null || true
        fi
        return
    fi

    if [[ -f /run/ai-agent.pid ]]; then
        local pid
        pid="$(cat /run/ai-agent.pid 2>/dev/null || true)"
        if [[ -n "$pid" ]]; then
            kill "$pid" 2>/dev/null || true
        fi
        rm -f /run/ai-agent.pid
    fi
    pkill -f "$INSTALL_DIR/backend/main.py" 2>/dev/null || true
}

restart_nginx() {
    nginx -t
    if systemd_is_running; then
        systemctl restart nginx
    elif command -v service >/dev/null 2>&1; then
        service nginx restart || service nginx start || nginx -s reload 2>/dev/null || nginx
    else
        nginx -s reload 2>/dev/null || nginx
    fi
}

verify_backend() {
    sleep 2
    if curl -fsS "http://127.0.0.1:$BACKEND_PORT/health" >/dev/null 2>&1; then
        return
    fi

    if systemd_is_running; then
        journalctl -u ai-agent -n 80 --no-pager || true
    elif [[ -f /var/log/ai-agent/backend.log ]]; then
        tail -n 80 /var/log/ai-agent/backend.log || true
    fi
    error "ai-agent backend failed to start"
}

start_backend_without_systemd() {
    log "systemd is not available; starting backend as a background process."
    mkdir -p /var/log/ai-agent /run
    chown ai-agent:ai-agent /var/log/ai-agent
    rm -f /run/ai-agent.pid /tmp/ai-agent.pid

    local backend_dir log_file pid_file
    backend_dir="$(printf "%q" "$INSTALL_DIR/backend")"
    log_file="$(printf "%q" "/var/log/ai-agent/backend.log")"
    pid_file="$(printf "%q" "/tmp/ai-agent.pid")"

    run_as_ai_agent bash -c "cd $backend_dir && nohup ./venv/bin/python main.py > $log_file 2>&1 & echo \$! > $pid_file"
    if [[ -f /tmp/ai-agent.pid ]]; then
        mv /tmp/ai-agent.pid /run/ai-agent.pid
    fi
    verify_backend
}

# --- Argument Parsing ---
while [[ $# -gt 0 ]]; do
    case $1 in
        --yes) AUTO_YES="yes"; shift ;;
        --install-dir) INSTALL_DIR="$2"; shift 2 ;;
        --backend-port) BACKEND_PORT="$2"; BACKEND_PORT_EXPLICIT="yes"; shift 2 ;;
        --domain) DOMAIN="$2"; shift 2 ;;
        --no-nginx) INSTALL_NGINX="no"; shift ;;
        *) shift ;;
    esac
done

if [[ ! -t 0 && "$AUTO_YES" == "no" ]]; then
    AUTO_YES="yes"
fi

# --- Prerequisites ---
if [[ $EUID -ne 0 ]]; then
   error "This script must be run as root/sudo"
fi

log "Checking OS compatibility..."
if [ -f /etc/debian_version ]; then
    OS="debian"
else
    error "This script currently only supports Debian/Ubuntu"
fi

# --- Detect local IP (best available interface, fallback chain) ---------------
detect_local_ip() {
    # 1. IP of the default-route interface (most reliable on single-NIC machines)
    local ip
    ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}')
    [[ -n "$ip" ]] && echo "$ip" && return

    # 2. First non-loopback IPv4 from ip addr
    ip=$(ip -4 addr show 2>/dev/null \
        | awk '/inet / && !/127\./ {gsub("/.*","",$2); print $2; exit}')
    [[ -n "$ip" ]] && echo "$ip" && return

    # 3. hostname -I fallback
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    [[ -n "$ip" ]] && echo "$ip" && return

    echo "_"
}

DETECTED_IP=$(detect_local_ip)
if [[ "$AUTO_YES" == "yes" && "$DOMAIN" == "_" ]]; then
    DOMAIN="$DETECTED_IP"
fi

node_version_is_supported() {
    if ! command -v node >/dev/null 2>&1; then
        return 1
    fi

    local version major minor
    version="$(node -v | sed 's/^v//')"
    major="${version%%.*}"
    minor="${version#*.}"
    minor="${minor%%.*}"

    # Vite requires Node.js 20.19+ or 22.12+.
    if (( major == 20 && minor >= 19 )); then
        return 0
    fi
    if (( major == 22 && minor >= 12 )); then
        return 0
    fi
    if (( major > 22 )); then
        return 0
    fi
    return 1
}

install_supported_nodejs() {
    if node_version_is_supported; then
        log "Node.js $(node -v) is supported."
        return
    fi

    log "Installing Node.js 22 for the frontend build..."
    echo "nodejs" >> "$PACKAGE_MANIFEST"
    apt-get remove -y nodejs npm >/dev/null 2>&1 || true
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y nodejs

    if ! node_version_is_supported; then
        error "Node.js installation failed or installed an unsupported version: $(node -v 2>/dev/null || echo 'not found')"
    fi
    log "Using Node.js $(node -v) and npm $(npm -v)."
}

port_is_free() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        ! ss -ltn "( sport = :$port )" | grep -q ":$port"
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
        error "Backend port $BACKEND_PORT is already in use"
    fi

    local candidate
    for candidate in $(seq "$((BACKEND_PORT + 1))" 8099); do
        if port_is_free "$candidate"; then
            log "Backend port $BACKEND_PORT is already in use; using free port $candidate instead."
            BACKEND_PORT="$candidate"
            return
        fi
    done

    describe_port_owner "$BACKEND_PORT"
    error "No free backend port found in range $BACKEND_PORT-8099"
}

# --- Interactive Setup ---
if [[ "$AUTO_YES" == "no" ]]; then
    echo -e "${BLUE}--- AI Agent Production Setup ---${NC}"
    read -p "Install path [$INSTALL_DIR]: " input_dir
    INSTALL_DIR=${input_dir:-$INSTALL_DIR}

    read -p "Backend port [$BACKEND_PORT]: " input_port
    BACKEND_PORT=${input_port:-$BACKEND_PORT}

    read -p "Configure Nginx as reverse proxy? (y/n) [y]: " input_nginx
    [[ "$input_nginx" == "n" ]] && INSTALL_NGINX="no"

    if [[ "$INSTALL_NGINX" == "yes" ]]; then
        read -p "Domain or Server IP [$DETECTED_IP]: " input_domain
        DOMAIN=${input_domain:-$DETECTED_IP}
    fi

fi

# --- System Dependencies ---
log "Installing system dependencies..."
apt-get update
for package in git curl ca-certificates gnupg python3-venv python3-pip nginx iproute2; do
    remember_if_missing "$package"
done
apt-get install -y git curl ca-certificates gnupg python3 python3-venv python3-pip nginx iproute2
install_supported_nodejs

# When this script is run via "curl | bash", it is not located inside the
# repository. In that mode, fetch a temporary copy of the project first.
if [[ ! -d "$PROJECT_SOURCE/backend" || ! -d "$PROJECT_SOURCE/frontend" ]]; then
    log "Installer is running outside a local clone; downloading project source..."
    TMP_SOURCE="$(mktemp -d)"
    git clone --depth 1 "$REPO_URL" "$TMP_SOURCE"
    PROJECT_SOURCE="$TMP_SOURCE"
fi

if ! [[ "$BACKEND_PORT" =~ ^[0-9]+$ ]]; then
    error "Invalid backend port: $BACKEND_PORT"
fi

if [[ -z "$DOMAIN" ]]; then
    DOMAIN="$DETECTED_IP"
fi

# Stop previous app instances before replacing files or checking port usage.
stop_previous_app
resolve_backend_port

# --- User Setup ---
log "Creating system user..."
if ! id "ai-agent" &>/dev/null; then
    useradd -m -s /bin/bash ai-agent
fi

# --- Project Setup ---
log "Setting up project in $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
cp -r "$PROJECT_SOURCE/." "$INSTALL_DIR/"
rm -rf "$INSTALL_DIR/backend/venv" "$INSTALL_DIR/frontend/node_modules" "$INSTALL_DIR/frontend/dist"
sort -u "$PACKAGE_MANIFEST" > "$INSTALL_DIR/.ai-agent-installed-packages"
chmod +x "$INSTALL_DIR"/*.sh 2>/dev/null || true
chown -R ai-agent:ai-agent "$INSTALL_DIR"

# Configure git to trust this directory (prevents "dubious ownership" error on upgrades)
git config --global --add safe.directory "$INSTALL_DIR"

# --- Backend Setup ---
log "Configuring Python backend..."
cd "$INSTALL_DIR/backend"
run_as_ai_agent python3 -m venv venv
run_as_ai_agent ./venv/bin/python -m pip install --upgrade pip
run_as_ai_agent ./venv/bin/python -m pip install -r requirements.txt

# .env configuration
if [[ ! -f .env ]]; then
    run_as_ai_agent cp .env.example .env
fi
run_as_ai_agent sed -i "s|API_PORT=.*|API_PORT=$BACKEND_PORT|" .env

# --- Frontend Setup ---
log "Building frontend (this may take a few minutes)..."
cd "$INSTALL_DIR/frontend"
mkdir -p /home/ai-agent/.npm
chown -R ai-agent:ai-agent /home/ai-agent/.npm
run_as_ai_agent npm install --no-audit --no-fund --silent
run_as_ai_agent env NODE_OPTIONS="--max-old-space-size=4096" npm run build --silent

# --- Backend runtime ---
if [[ "$ENABLE_SYSTEMD" == "yes" ]] && systemd_is_running; then
    log "Configuring systemd service..."
    SERVICE_FILE="/etc/systemd/system/ai-agent.service"
    cp "$INSTALL_DIR/deploy/ai-agent.service" "$SERVICE_FILE"
    
    # Replace placeholders
    sed -i "s|/opt/ai-agent|$INSTALL_DIR|g" "$SERVICE_FILE"
    
    systemctl daemon-reload
    systemctl enable ai-agent
    systemctl restart ai-agent
    verify_backend
else
    start_backend_without_systemd
fi

# --- Nginx Setup ---
if [[ "$INSTALL_NGINX" == "yes" ]]; then
    log "Configuring Nginx..."
    NGINX_CONF="/etc/nginx/sites-available/ai-agent"
    cp "$INSTALL_DIR/deploy/nginx.conf.template" "$NGINX_CONF"
    
    # Replace placeholders
    sed -i "s|/opt/ai-agent|$INSTALL_DIR|g" "$NGINX_CONF"
    sed -i "s|8000|$BACKEND_PORT|g" "$NGINX_CONF"
    sed -i "s|server_name _;|server_name $DOMAIN;|g" "$NGINX_CONF"
    
    ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/
    rm -f /etc/nginx/sites-enabled/default
    restart_nginx
fi

success "Installation completed successfully!"
echo -e "\nAccess the app at: http://$DOMAIN"
echo -e "Backend running on port: $BACKEND_PORT"
echo -e "\nUseful commands:"
if systemd_is_running; then
    echo -e "  - View logs: sudo journalctl -u ai-agent -f"
    echo -e "  - Restart: sudo systemctl restart ai-agent"
else
    echo -e "  - View logs: sudo tail -f /var/log/ai-agent/backend.log"
    echo -e "  - Restart: sudo pkill -F /run/ai-agent.pid 2>/dev/null || true; sudo bash $INSTALL_DIR/install.sh --yes --backend-port $BACKEND_PORT --domain $DOMAIN"
fi
echo -e "  - Upgrade: sudo bash $INSTALL_DIR/upgrade.sh"
echo -e "  - Uninstall: sudo bash $INSTALL_DIR/uninstall.sh"

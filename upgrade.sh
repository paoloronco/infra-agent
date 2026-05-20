#!/bin/bash
# ============================================================
# AI Agent SSH & Troubleshooting — Upgrader
# Usage: sudo bash /opt/ai-agent/upgrade.sh
# ============================================================
# Design goals:
#   - Zero manual intervention required
#   - Idempotent: safe to run multiple times
#   - Never leaves the system in a broken state
#   - Auto-restarts the service and verifies it comes up
# ============================================================

set -Eeo pipefail
trap 'on_error $LINENO $?' ERR

INSTALL_DIR=$(dirname "$(readlink -f "$0")")
SERVICE_NAME="ai-agent"
APP_USER="ai-agent"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'
YELLOW='\033[0;33m'; BOLD='\033[1m'; NC='\033[0m'

log()     { echo -e "${BLUE}[INFO]${NC}  $1"; }
success() { echo -e "${GREEN}[OK]${NC}   $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1" >&2; exit 1; }
step()    { echo -e "\n${BOLD}${BLUE}▶ $1${NC}"; }

on_error() {
    local line=$1 code=$2
    echo -e "\n${RED}[ERROR]${NC} Upgrade failed at line $line (exit code $code)"
    echo -e "  Run: ${BOLD}journalctl -u ${SERVICE_NAME} -n 40 --no-pager${NC} to inspect the service."
    exit "$code"
}

# ── Root check ────────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || error "Run as root: sudo bash $0"

echo -e "\n${BOLD}${BLUE}╔══════════════════════════════════╗"
echo -e "║   AI Agent Upgrader              ║"
echo -e "╚══════════════════════════════════╝${NC}"
log "Install directory : $INSTALL_DIR"
log "Service name      : $SERVICE_NAME"
log "App user          : $APP_USER"

cd "$INSTALL_DIR"

# ── Sanity checks ─────────────────────────────────────────────────────────────
step "Pre-flight checks"

git -C "$INSTALL_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || error "$INSTALL_DIR is not a git repository. Run install.sh first."

[[ -d "$INSTALL_DIR/backend/venv" ]] \
    || error "Python venv not found. Run install.sh first."

[[ -d "$INSTALL_DIR/frontend" ]] \
    || error "Frontend directory not found. Run install.sh first."

id "$APP_USER" >/dev/null 2>&1 \
    || error "System user '$APP_USER' not found. Run install.sh first."

git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true
success "Pre-flight checks passed."

# ── Clean working tree so git pull never gets blocked ─────────────────────────
step "Preparing working tree"

# Any local changes to *.sh files are discarded: the repo versions are always
# correct (they were just updated). Backend/frontend local changes are stashed
# as a safety net but should not exist in a normal production deployment.
STASHED=0

# 1. Reset root-level shell scripts — these conflict on every upgrade because
#    the previous run's timestamp or path edits are irrelevant.
if ! git -C "$INSTALL_DIR" diff --quiet -- '*.sh' 2>/dev/null; then
    log "Resetting local *.sh changes (accepting repo versions)..."
    git -C "$INSTALL_DIR" checkout -- '*.sh' 2>/dev/null || true
fi

# 2. Stash any remaining code changes (backend/ frontend/) if present.
if [[ -n "$(git -C "$INSTALL_DIR" status --porcelain -- backend/ frontend/ 2>/dev/null)" ]]; then
    warn "Uncommitted changes in backend/ or frontend/ — stashing..."
    git -C "$INSTALL_DIR" stash push -u \
        -m "ai-agent upgrade $(date +%Y%m%d-%H%M%S)" \
        -- backend/ frontend/
    STASHED=1
fi

success "Working tree is clean."

# ── Database safety snapshot ──────────────────────────────────────────────────
step "Backing up local database"

DB_FILE="$INSTALL_DIR/backend/data/app.db"
if [[ -f "$DB_FILE" ]]; then
    DB_BACKUP="$INSTALL_DIR/backend/data/app.db.pre-upgrade-$(date +%Y%m%d-%H%M%S)"
    cp -a "$DB_FILE" "$DB_BACKUP"
    chown "${APP_USER}:${APP_USER}" "$DB_BACKUP" 2>/dev/null || true
    success "Database snapshot: $DB_BACKUP"
else
    warn "No local SQLite database found at $DB_FILE; skipping DB snapshot."
fi

# ── Pull latest code ──────────────────────────────────────────────────────────
step "Pulling latest code"

BRANCH=$(git -C "$INSTALL_DIR" rev-parse --abbrev-ref HEAD)
OLD_COMMIT=$(git -C "$INSTALL_DIR" rev-parse --short HEAD)

log "Branch: $BRANCH  |  Current: $OLD_COMMIT"
git -C "$INSTALL_DIR" fetch --quiet origin

# Check how many commits we are behind
BEHIND=$(git -C "$INSTALL_DIR" rev-list --count HEAD..origin/"$BRANCH" 2>/dev/null || echo 0)

if [[ "$BEHIND" -eq 0 ]]; then
    warn "Already up to date ($OLD_COMMIT). Continuing to ensure deps and build are current."
else
    log "Pulling $BEHIND new commit(s)..."
    git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
    NEW_COMMIT=$(git -C "$INSTALL_DIR" rev-parse --short HEAD)
    success "Updated $OLD_COMMIT → $NEW_COMMIT"
fi

chmod +x "$INSTALL_DIR"/*.sh 2>/dev/null || true

# ── Restore stash (if any) ────────────────────────────────────────────────────
if [[ "$STASHED" -eq 1 ]]; then
    log "Restoring stashed backend/frontend changes..."
    if ! git -C "$INSTALL_DIR" stash pop 2>/dev/null; then
        # Conflict during pop: the repo version is authoritative.
        # Clean up and drop the stash cleanly.
        git -C "$INSTALL_DIR" checkout -- . 2>/dev/null || true
        git -C "$INSTALL_DIR" stash drop 2>/dev/null || true
        warn "Stash pop had conflicts — repo versions kept. Local changes discarded."
    else
        success "Stash restored successfully."
    fi
fi

# ── Backend: Python dependencies ──────────────────────────────────────────────
step "Upgrading backend dependencies"

VENV="$INSTALL_DIR/backend/venv"

# Fix pip cache ownership to suppress the 'cache not writable' warning
PIP_CACHE_DIR="/home/${APP_USER}/.cache/pip"
mkdir -p "$PIP_CACHE_DIR"
chown -R "${APP_USER}:${APP_USER}" "$PIP_CACHE_DIR" 2>/dev/null || true

cd "$INSTALL_DIR/backend"

# Upgrade pip itself quietly, then upgrade all requirements
sudo -H -u "$APP_USER" "$VENV/bin/pip" install --quiet --upgrade pip 2>/dev/null || true
sudo -H -u "$APP_USER" "$VENV/bin/pip" install --quiet --upgrade -r requirements.txt

success "Backend dependencies up to date."

# ── Frontend: build ───────────────────────────────────────────────────────────
step "Rebuilding frontend"

cd "$INSTALL_DIR/frontend"

# Install/update npm dependencies
sudo -H -u "$APP_USER" npm install --no-audit --no-fund --silent

# Build (suppress the chunk-size warning — it's cosmetic only)
sudo -H -u "$APP_USER" \
    env NODE_OPTIONS="--max-old-space-size=4096" \
    npm run build 2>&1 | grep -v "Some chunks are larger" | grep -v "Using dynamic import" \
                       | grep -v "Use build.rollupOptions" | grep -v "Adjust chunk size" \
                       | grep -v "build.chunkSizeWarningLimit" || true

success "Frontend rebuilt."

# ── Nginx: refresh reverse proxy routes ───────────────────────────────────────
step "Refreshing Nginx reverse proxy config"

NGINX_CONF="/etc/nginx/sites-available/${SERVICE_NAME}"
if command -v nginx >/dev/null 2>&1 && [[ -f "$NGINX_CONF" && -f "$INSTALL_DIR/deploy/nginx.conf.template" ]]; then
    BACKEND_PORT=$(grep -Eo 'proxy_pass http://localhost:[0-9]+' "$NGINX_CONF" | head -n1 | awk -F: '{print $NF}')
    BACKEND_PORT=${BACKEND_PORT:-8000}
    SERVER_NAME=$(grep -E '^\s*server_name\s+' "$NGINX_CONF" | head -n1 | sed -E 's/^\s*server_name\s+([^;]+);/\1/')
    SERVER_NAME=${SERVER_NAME:-_}

    cp "$INSTALL_DIR/deploy/nginx.conf.template" "$NGINX_CONF"
    sed -i "s|/opt/ai-agent|$INSTALL_DIR|g" "$NGINX_CONF"
    sed -i "s|8000|$BACKEND_PORT|g" "$NGINX_CONF"
    sed -i "s|server_name _;|server_name $SERVER_NAME;|g" "$NGINX_CONF"

    nginx -t && systemctl reload nginx
    success "Nginx config refreshed."
else
    warn "Nginx site config not found; skipping reverse proxy refresh."
fi

# ── Restart service ───────────────────────────────────────────────────────────
step "Restarting service"

# Reliable detection: list-unit-files works even for inactive/disabled units
# and in container environments where list-units may behave differently.
SERVICE_KNOWN=0
if systemctl list-unit-files "${SERVICE_NAME}.service" 2>/dev/null \
        | grep -q "^${SERVICE_NAME}.service"; then
    SERVICE_KNOWN=1
elif [[ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]]; then
    systemctl daemon-reload 2>/dev/null || true
    SERVICE_KNOWN=1
fi

if [[ "$SERVICE_KNOWN" -eq 1 ]]; then
    log "Restarting ${SERVICE_NAME}..."
    systemctl restart "${SERVICE_NAME}"

    # Wait up to 20 seconds for the service to become active
    READY=0
    for i in {1..10}; do
        sleep 2
        if systemctl is-active --quiet "${SERVICE_NAME}"; then
            READY=1
            break
        fi
    done

    if [[ "$READY" -eq 1 ]]; then
        success "Service is running."
    else
        echo ""
        warn "Service did not start within 20s. Last 30 log lines:"
        journalctl -u "${SERVICE_NAME}" -n 30 --no-pager 2>/dev/null || true
        error "Service failed to start — check logs above."
    fi
else
    warn "Service '${SERVICE_NAME}' is not installed — skipping restart."
    warn "To register the service: sudo bash $INSTALL_DIR/install.sh"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
FINAL_COMMIT=$(git -C "$INSTALL_DIR" rev-parse --short HEAD)

echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════╗"
echo -e "║   Upgrade complete!              ║"
echo -e "╚══════════════════════════════════╝${NC}"
success "Running commit : $FINAL_COMMIT"
echo -e "  Logs   : ${BOLD}journalctl -u ${SERVICE_NAME} -f${NC}"
echo -e "  Status : ${BOLD}systemctl status ${SERVICE_NAME}${NC}"
echo ""

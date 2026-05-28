# ─── Stage 1: Build React frontend ───────────────────────────────────────────
FROM node:20-alpine AS frontend-builder
WORKDIR /build/frontend

COPY frontend/package*.json ./
RUN npm ci --prefer-offline

COPY frontend/ ./
# VITE_API_URL is intentionally unset → empty string → relative paths proxied by nginx
RUN npm run build

# ─── Stage 2: Production image ────────────────────────────────────────────────
FROM python:3.12-slim

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      nginx \
      supervisor \
      openssh-client \
      curl \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps before copying source (maximises layer cache reuse)
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./

# Copy built frontend assets
COPY --from=frontend-builder /build/frontend/dist /app/frontend/dist

# Nginx + supervisor configuration
COPY docker/nginx.conf /etc/nginx/sites-available/default
RUN rm -f /etc/nginx/sites-enabled/default \
 && ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default

COPY docker/supervisord.conf /etc/supervisor/conf.d/infra-agent.conf

# Runtime directories (data is mounted as a volume)
RUN mkdir -p \
      /app/backend/data \
      /app/backend/data/ssh_keys \
      /app/backend/logs \
      /app/backend/uploads \
 && chmod 700 /app/backend/data/ssh_keys

EXPOSE 80

# Persist database and SSH keys across container restarts
VOLUME ["/app/backend/data"]

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/infra-agent.conf"]

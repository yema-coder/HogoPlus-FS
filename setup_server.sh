#!/usr/bin/env bash
# ============================================================================
# HOGOPLUS-FS — one-shot EC2 server setup (Ubuntu 24.04, ap-south-1).
# Installs Docker + compose, nginx reverse proxy + Let's Encrypt TLS, UFW.
# IDEMPOTENT: safe to re-run.
#
#   sudo bash setup_server.sh <api-domain> <letsencrypt-email> [app_dir]
#   e.g. sudo bash setup_server.sh api.hogoplus.com ops@hogoplus.com
#
# Run this AFTER you have cloned the repo into the app dir and created .env
# (see MUMBAI_MIGRATION.md). Re-run any time to reconcile config.
# ============================================================================
set -euo pipefail

DOMAIN="${1:-}"
EMAIL="${2:-}"
APP_DIR="${3:-/opt/hogoplus}"

if [[ -z "$DOMAIN" || -z "$EMAIL" ]]; then
  echo "Usage: sudo bash setup_server.sh <api-domain> <letsencrypt-email> [app_dir]" >&2
  exit 1
fi
if [[ $EUID -ne 0 ]]; then echo "Run with sudo/root." >&2; exit 1; fi

echo ">> [1/6] Base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg nginx ufw

echo ">> [2/6] Docker Engine + compose plugin"
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
# let the default 'ubuntu' user run docker without sudo (idempotent)
id ubuntu >/dev/null 2>&1 && usermod -aG docker ubuntu || true

echo ">> [3/6] App directory: $APP_DIR"
mkdir -p "$APP_DIR"
if [[ ! -f "$APP_DIR/docker-compose.yml" ]]; then
  echo "   WARNING: $APP_DIR/docker-compose.yml not found."
  echo "   Clone the repo here and create .env BEFORE 'docker compose up' (see runbook)."
fi

echo ">> [4/6] systemd unit (brings the stack up on boot; compose also restart:always)"
cat > /etc/systemd/system/hogoplus.service <<UNIT
[Unit]
Description=HOGOPLUS-FS backend (docker compose)
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/docker compose up -d --build
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable hogoplus.service

echo ">> [5/6] nginx reverse proxy for $DOMAIN"
cat > /etc/nginx/sites-available/hogoplus.conf <<NGINX
server {
    listen 80;
    server_name $DOMAIN;

    client_max_body_size 100M;          # photo/video incident uploads (>=50MB required)
    client_body_timeout 120s;

    gzip on;
    gzip_types application/json application/javascript text/css text/plain image/svg+xml;
    gzip_min_length 1000;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }
}
NGINX
ln -sf /etc/nginx/sites-available/hogoplus.conf /etc/nginx/sites-enabled/hogoplus.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo ">> [6/6] TLS (certbot) + firewall"
if ! command -v certbot >/dev/null 2>&1; then
  apt-get install -y -qq certbot python3-certbot-nginx
fi
# obtain/renew cert + rewrite the vhost for 443 (idempotent; skips if valid cert exists)
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect || \
  echo "   certbot did not complete — ensure DNS A-record for $DOMAIN points here, then re-run."

ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo ""
echo "== DONE =="
echo "Next: cd $APP_DIR && (fill .env) && sudo systemctl start hogoplus  # or: docker compose up -d --build"
echo "Verify: curl -s https://$DOMAIN/api/health"

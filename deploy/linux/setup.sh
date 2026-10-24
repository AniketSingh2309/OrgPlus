#!/usr/bin/env bash
# Org+ on one Ubuntu 24.04 server (e.g. AWS EC2): Postgres 16, API, worker, web app and
# Caddy (automatic HTTPS). Safe to run again: it also deploys updated code.
#
#   sudo bash deploy/linux/setup.sh orgplus.example.com head@example.com
#
#   $1  the domain people will open (its DNS A record must point at this server)
#   $2  optional: ORG_ADMINS (comma-separated emails with full access)
#
# Layout: code in /opt/orgplus, secrets in /opt/orgplus/.env (root:orgplus, 0640),
# services run as the unprivileged user "orgplus".
set -euo pipefail

DOMAIN="${1:?usage: sudo bash deploy/linux/setup.sh <domain> [org-admin-emails]}"
ORG_ADMINS="${2:-}"
APP=/opt/orgplus
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

step "System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q ca-certificates curl gnupg rsync python3 python3-venv python3-dev \
  build-essential postgresql postgresql-contrib debian-keyring debian-archive-keyring apt-transport-https
if ! command -v node >/dev/null || [ "$(node -v | cut -d. -f1 | tr -d v)" -lt 20 ]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -q nodejs
fi
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -y -q caddy
fi

step "Service user and code in $APP"
id orgplus >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin orgplus
mkdir -p "$APP"
if [ "$SRC" != "$APP" ]; then
  rsync -a --delete \
    --exclude .env --exclude 'secrets/*' --exclude 'data/*' \
    --exclude node_modules --exclude .next --exclude .venv --exclude '__pycache__' \
    --exclude '*.egg-info' --exclude .pytest_cache --exclude .mypy_cache --exclude .ruff_cache \
    "$SRC/" "$APP/"
fi
mkdir -p "$APP/data" "$APP/secrets"

step "Postgres: localhost only, passwordless roles locked down by pg_hba"
PGV=$(ls /etc/postgresql | sort -V | tail -1)
[ "${PGV%%.*}" -ge 16 ] || { echo "Postgres 16+ required (found $PGV)"; exit 1; }
PGCONF=/etc/postgresql/$PGV/main
sed -i "s/^#\?listen_addresses.*/listen_addresses = 'localhost'/" "$PGCONF/postgresql.conf"
install -m 640 -o postgres -g postgres "$APP/deploy/postgres/pg_hba.linux.conf" "$PGCONF/pg_hba.conf"
systemctl restart postgresql
sudo -u postgres psql -q -v ON_ERROR_STOP=1 -f "$APP/deploy/postgres/init.sql"

step "Settings ($APP/.env)"
if [ ! -f "$APP/.env" ]; then
  KEY=$(python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())')
  SECRET=$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')
  cat > "$APP/.env" <<EOF
# Org+ production settings. Never commit or share this file. Back up CREDENTIAL_ENC_KEY.
APP_URL=https://$DOMAIN
NEXTAUTH_URL=https://$DOMAIN
API_PUBLIC_URL=https://$DOMAIN
WEB_ORIGINS=https://$DOMAIN
API_INTERNAL_URL=http://127.0.0.1:8000
NEXTAUTH_SECRET=$SECRET
CREDENTIAL_ENC_KEY=$KEY
ORG_ADMINS=$ORG_ADMINS
CONTROL_DATABASE_URL=postgresql://orgplus_control@localhost:5432/orgplus_control
ORG_DATABASE_URL_TEMPLATE=postgresql://{role}@localhost:5432/{db}
DEV_AUTH_BYPASS=false
AUTH_EMAIL_LOG_LINKS=false
LOG_LEVEL=INFO
# Optional email (password-reset links, weekly digest):
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=
EOF
  echo "created $APP/.env (new secrets generated)"
else
  echo "keeping existing $APP/.env"
fi
chown -R orgplus:orgplus "$APP"
chown root:orgplus "$APP/.env" && chmod 640 "$APP/.env"
chmod 750 "$APP/secrets"

step "Backend (Python virtualenv)"
sudo -u orgplus python3 -m venv "$APP/backend/.venv"
sudo -u orgplus "$APP/backend/.venv/bin/pip" install -q --upgrade pip
# Editable install: migrations and data paths are resolved from the source tree.
sudo -u orgplus "$APP/backend/.venv/bin/pip" install -q -e "$APP/backend"

step "Web app (npm build)"
cd "$APP/web"
sudo -u orgplus npm ci --no-audit --no-fund --loglevel=error
sudo -u orgplus bash -c "set -a; . '$APP/.env'; set +a; NEXT_TELEMETRY_DISABLED=1 ./node_modules/.bin/next build"

step "Services (systemd)"
for unit in orgplus-api orgplus-worker orgplus-web; do
  install -m 644 "$APP/deploy/linux/$unit.service" "/etc/systemd/system/$unit.service"
done
systemctl daemon-reload
# The worker first: on start it creates/migrates every database, then the API and web.
systemctl enable --now orgplus-worker
systemctl restart orgplus-worker
for i in $(seq 1 60); do
  journalctl -u orgplus-worker --since "-2min" -o cat | grep -q "databases ready" && break
  sleep 2
done
systemctl enable --now orgplus-api orgplus-web
systemctl restart orgplus-api orgplus-web

step "HTTPS (Caddy)"
sed "s/{\$DOMAIN}/$DOMAIN/" "$APP/deploy/linux/Caddyfile" > /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy

step "Check"
for i in $(seq 1 30); do curl -sf http://127.0.0.1:8000/api/health >/dev/null && break; sleep 2; done
curl -s http://127.0.0.1:8000/api/health && echo
for s in postgresql orgplus-worker orgplus-api orgplus-web caddy; do
  printf '%-16s %s\n' "$s" "$(systemctl is-active $s)"
done
cat <<EOF

Org+ is running. Open https://$DOMAIN/signup to create the first account.
  Logs:     journalctl -u orgplus-api -f   (or orgplus-worker, orgplus-web)
  Settings: sudo nano $APP/.env   then: sudo systemctl restart orgplus-api orgplus-worker orgplus-web
  Update:   copy the new code to the server and run this script again.
EOF

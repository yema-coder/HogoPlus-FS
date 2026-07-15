#!/usr/bin/env bash
# Sandbox recovery after a pod reset (system packages wiped, /app preserved).
# Restores PostgreSQL 16 + pgvector + Redis, recreates roles/DBs, restores the
# latest R2 backup and restarts all supervised services (incl. local MongoDB,
# which the Emergent deploy pipeline needs to be running).
set -euo pipefail

if ! id postgres >/dev/null 2>&1; then
  echo "== Installing PostgreSQL 16 + pgvector + Redis (PGDG) =="
  install -d /usr/share/postgresql-common/pgdg
  curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    https://www.postgresql.org/media/keys/ACCC4CF8.asc
  echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    postgresql-16 postgresql-16-pgvector postgresql-client-16 redis-server
fi

if [ ! -S /var/run/supervisor.sock ]; then
  # kill stray daemons only when supervisord isn't managing them yet
  pkill -f "redis-server|/usr/lib/postgresql" 2>/dev/null || true
  sleep 1
  echo "== Starting supervisord =="
  /usr/bin/supervisord -c /etc/supervisor/supervisord.conf || true
  sleep 8
fi

echo "== Waiting for PostgreSQL =="
for _ in $(seq 1 15); do
  sudo -u postgres psql -c "SELECT 1" >/dev/null 2>&1 && break
  sleep 2
done

echo "== Ensuring role + databases =="
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='hogo'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE ROLE hogo LOGIN PASSWORD 'hogo_secret' SUPERUSER;"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='hogoplus'" | grep -q 1 || \
  sudo -u postgres createdb -O hogo hogoplus
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='hogoplus_test'" | grep -q 1 || \
  sudo -u postgres createdb -O hogo hogoplus_test
sudo -u postgres psql -d hogoplus -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null
sudo -u postgres psql -d hogoplus_test -c "CREATE EXTENSION IF NOT EXISTS vector;" >/dev/null

EMP=$(sudo -u postgres psql -d hogoplus -tc "SELECT count(*) FROM employees" 2>/dev/null | tr -d ' ' || echo 0)
if [ "${EMP:-0}" = "0" ] || [ -z "${EMP}" ]; then
  echo "== Restoring latest backup from R2 =="
  cd /app/backend && /root/.venv/bin/python scripts/restore_latest.py --latest --yes
fi

echo "== Restarting services =="
supervisorctl restart backend celery_worker celery_beat expo mongodb >/dev/null || true
sleep 12
supervisorctl status || true
curl -s localhost:8001/api/health || true
echo
mongosh --quiet --eval "db.adminCommand('listDatabases').databases.map(d=>d.name).join(',')" || echo "mongod NOT reachable"

# syntax=docker/dockerfile:1
# ============================================================================
# HOGOPLUS-FS backend — single production image for AWS Mumbai (ap-south-1).
# Serves FastAPI + in-process APScheduler + the webdash SPA at /api/dash/.
# Build from the REPO ROOT:  docker compose build   (context = repo root)
# NO application code changes are required for containerization — this image
# runs the exact same code as the Emergent deployment (server:app).
# ============================================================================

# ---------- Stage 1: build the MD Command Center (webdash) static bundle -----
FROM node:20-slim AS webdash
WORKDIR /webdash
# copy manifest first for layer caching (lockfile optional — npm install is resilient)
COPY webdash/package.json ./
RUN npm install --no-audit --no-fund
COPY webdash/ ./
# vite.config sets base:"/api/dash/" and outDir ../backend/webdash_dist; we override
# --outDir to a clean path so stage 2 can copy it to the location app/main.py expects.
RUN npx vite build --outDir /webdash_dist --emptyOutDir

# ---------- Stage 2: Python runtime ------------------------------------------
FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# System deps:
#   - postgresql-client-18  → pg_dump for POST /api/admin/backup-now (Neon runs PG 18;
#                             pg_dump must be >= server major or it aborts). A pure-Python
#                             dump fallback exists, but v18 gives a proper pg_dump backup.
#   - libgomp1              → onnxruntime (fastembed) runtime dependency
#   - libpq5                → asyncpg / libpq client
#   - curl                  → container HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates gnupg libpq5 libgomp1 \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update && apt-get install -y --no-install-recommends postgresql-client-18 \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# emergentintegrations lives on the Emergent package index (not public PyPI) — the
# extra-index-url is REQUIRED or the build fails to resolve it.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ -r requirements.txt \
 && pip install "uvicorn[standard]==0.25.0"

# application code (server:app -> app.main:app)
COPY backend/ /app/backend/

# webdash static bundle — FastAPI serves it from ../webdash_dist at /api/dash/
COPY --from=webdash /webdash_dist /app/backend/webdash_dist

EXPOSE 8001

# t3.medium (2 vCPU) → 2 uvicorn workers. Each worker starts its own APScheduler,
# but every scheduled job first takes a Redis NX lock (jobs:lock:<name>) on the shared
# Upstash Redis, so jobs execute ONCE globally across all workers AND all hosts.
# --proxy-headers/--forwarded-allow-ips: nginx terminates TLS and forwards X-Forwarded-*.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001", \
     "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]

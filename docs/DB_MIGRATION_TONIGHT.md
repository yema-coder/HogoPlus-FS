# TONIGHT'S CUTOVER — Neon (Singapore) → RDS PostgreSQL 18.4 ap-south-1 + local Redis
# Copy-paste runbook for the EC2 terminal (/opt/hogoplus, docker compose, nginx edge).
# Downtime budget: 10–15 min. Rollback: 3–5 min env flip.

## ANSWERS FIRST

**RDS version:** PostgreSQL **18.4** (GA on RDS, ap-south-1). pgvector **0.8.2** ships with it
(`CREATE EXTENSION vector`). Same major.minor as Neon 18.4 → pg_dump/pg_restore is a
same-version move, zero cross-version risk. If the console only offers another 18.x minor,
take the highest 18.x — any 18.x restores an 18.4 dump fine. Do NOT pick 17.

**Sizing:** `db.t4g.micro` (2 vCPU Graviton, 1 GiB) + **20 GiB gp3** (console minimum),
Single-AZ, storage autoscaling ON (max 50 GiB). ~₹1.1–1.3k/mo. 11 MB / 400 users is <1% load.
⚠️ micro's max_connections ≈ 110 — the Neon-era pools (2 workers × 150) would blow it. The
code is now env-tunable: set `DB_POOL_SIZE=10` + `DB_MAX_OVERFLOW=20` in .env at the flip
(step 14). That is 60 conns max — plenty at ≤5 ms RTT.

**RDS console choices (create now):**
- Engine PostgreSQL 18.4 · Template "Free tier"/Dev-Test · Single-AZ · db.t4g.micro · 20 GiB gp3
- Master username `hogo`, strong password · **Initial database name: `hogoplus`**
- Same VPC as the EC2, private subnets, **Public access: No**
- New security group `hogo-rds-sg`: inbound 5432 **from the EC2's security group only**
- Backups ON (7 days) · deletion protection ON · Performance Insights off (save $)

---

## PHASE A — Pre-flight (while RDS is creating, no downtime)

1. EC2 is ap-south-1 (co-location is the point):
   `curl -s http://169.254.169.254/latest/meta-data/placement/availability-zone`
2. PG 18 client tools (Ubuntu 24.04 ships v16 — its pg_dump refuses an 18 server):
   ```bash
   sudo apt install -y postgresql-common
   sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
   sudo apt install -y postgresql-client-18
   pg_dump --version   # must say 18.x
   ```
3. Shell vars (fill endpoint + passwords; note psql uses `sslmode`, the app URL uses `ssl`):
   ```bash
   export NEON_URL='postgresql://<neon-user>:<pw>@<neon-host>/<db>?sslmode=require'
   export RDS_URL='postgresql://hogo:<pw>@<rds-endpoint>.ap-south-1.rds.amazonaws.com:5432/hogoplus?sslmode=require'
   ```
4. RDS reachable + pgvector:
   ```bash
   psql "$RDS_URL" -c "SELECT version();"
   psql "$RDS_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"
   psql "$RDS_URL" -c "SELECT extversion FROM pg_extension WHERE extname='vector';"   # 0.8.x
   ```
5. **≤5 ms RTT proof** (record it; was ~217 ms to Neon):
   ```bash
   for i in 1 2 3 4 5; do psql "$RDS_URL" -c '\timing' -c 'SELECT 1;' 2>/dev/null | grep Time; done
   ```
   >20 ms ⇒ STOP, fix VPC/SG before any downtime.
6. Local Redis — in `/opt/hogoplus/docker-compose.yml` UNCOMMENT the `redis:` service block
   and the `redis_data:` volume line, then:
   ```bash
   cd /opt/hogoplus && docker compose up -d redis
   docker exec hogoplus-redis redis-cli ping   # PONG
   ```
   (Redis holds only self-expiring OTP/rate-limit/lock/batch state — nothing is copied from
   Upstash; anyone mid-OTP in the window just requests a new code.)
7. Rehearsal copy while app still runs (proves the whole path, no downtime):
   ```bash
   pg_dump "$NEON_URL" --no-owner --no-privileges -Fc -f /tmp/hogo_rehearsal.dump
   pg_restore --no-owner --clean --if-exists -d "$RDS_URL" /tmp/hogo_rehearsal.dump
   psql "$RDS_URL" -c "ANALYZE;"
   SOURCE_URL="$NEON_URL" TARGET_URL="$RDS_URL" python3 backend/scripts/verify_migration.py
   ```
   Row-count drift from live writes is fine in rehearsal; structure/extension/alembic checks
   must pass. Any other failure ⇒ fix before Phase B.

## PHASE B — Cutover (downtime starts; suggest 23:30 IST)

8. 30 min ahead: in-app 📣 Announce (trilingual): "app pauses ~15 min at 23:30 for maintenance".
9. Retire the old Emergent-hosted backend NOW: Emergent platform → Deployments/Publish panel →
   **Stop/Unpublish** `hogo-backend-phase1.emergent.host`. (It shares Neon + Upstash; with it
   gone, the per-host Redis NX scheduler lock is trivially safe — only the EC2's 2 uvicorn
   workers compete for `jobs:lock:*`, on the same local Redis. This was the documented
   precondition in docker-compose.yml.)
10. T-0 stop the app: `cd /opt/hogoplus && docker compose stop backend`
11. Confirm zero writers on Neon:
    ```bash
    psql "$NEON_URL" -c "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid();"
    ```
12. Final dump → restore → verify (the money step):
    ```bash
    pg_dump "$NEON_URL" --no-owner --no-privileges -Fc -f /tmp/hogo_final.dump
    pg_restore --no-owner --clean --if-exists -d "$RDS_URL" /tmp/hogo_final.dump
    psql "$RDS_URL" -c "ANALYZE;"
    SOURCE_URL="$NEON_URL" TARGET_URL="$RDS_URL" python3 backend/scripts/verify_migration.py
    ```
    → must print `ALL CHECKS PASS`. Anything else ⇒ PHASE C rollback.
13. Freeze Neon as the rollback anchor (read-only reference, kept 7 days):
    ```bash
    psql "$NEON_URL" -c "ALTER DATABASE $(psql "$NEON_URL" -tAc 'SELECT current_database()') SET default_transaction_read_only = on;"
    ```
14. Flip `/opt/hogoplus/.env` (backup first!):
    ```bash
    cp /opt/hogoplus/.env /opt/hogoplus/.env.neon-backup-$(date +%F)
    ```
    Edit these lines (leave everything else untouched):
    ```
    DATABASE_URL=postgresql+asyncpg://hogo:<pw>@<rds-endpoint>.ap-south-1.rds.amazonaws.com:5432/hogoplus?ssl=require
    REDIS_URL=redis://redis:6379/0
    CELERY_BROKER_URL=redis://redis:6379/1        # only if present in .env
    CELERY_RESULT_BACKEND=redis://redis:6379/2    # only if present in .env
    DB_POOL_SIZE=10
    DB_MAX_OVERFLOW=20
    ```
    (App URL uses `ssl=require`; psql URLs use `sslmode=require`. Redis host is `redis` —
    the compose service name.)
15. Recreate with new env + pull the latest code (includes the pool-size knob):
    ```bash
    cd /opt/hogoplus && git pull && docker compose up -d --build --force-recreate backend
    curl -fsS http://127.0.0.1:8001/api/health && curl -fsS https://api.hogoplus.in/api/health
    ```
16. Migration head: `docker exec hogoplus-backend alembic current` → `0013 (head)`.
17. Smoke (5 min, demo bubble — no SMS): D500 `+919000000500` OTP `123456` login → home loads ·
    demo punch-in → zone resolves · demo vehicle log → appears in register · webdash login OK.
18. Latency after: re-run step 5 probe + one authed `GET /api/incidents` — expect p50 <400 ms
    (was ~2.7 s). Save before/after numbers.
19. Watch 30–60 min: `docker logs -f hogoplus-backend` — no `too many connections`,
    no `redis` errors, scheduler lines firing once.

## PHASE C — ROLLBACK (only if 12/15/17 fails; ≈3–5 min)

```bash
cd /opt/hogoplus && docker compose stop backend
psql "$NEON_URL" -c "ALTER DATABASE $(psql "$NEON_URL" -tAc 'SELECT current_database()') SET default_transaction_read_only = off;"
cp /opt/hogoplus/.env.neon-backup-$(date +%F) /opt/hogoplus/.env
docker compose up -d --force-recreate backend
curl -fsS https://api.hogoplus.in/api/health
```
Then rerun the step-17 smoke. Upstash was never touched, so the old REDIS_URL in the backup
.env just works. Neon received zero writes after step 10 (app stopped before the dump), so
rollback is lossless. If you rolled back AFTER real users wrote to RDS, replay from RDS
`audit_events` (every mutation is audited) before reopening — with this window there are none.
Neon stays untouched (read-only) for 7 days; delete the project only after a clean week.

## WHAT USERS SEE DURING THE WINDOW
- API fully down from step 10 to step 15 (~10–15 min): app shows the offline strip /
  network-error retry screens. No crash, no data loss.
- Punch-ins attempted in the window queue in the offline outbox and auto-submit after.
- Anyone mid-OTP must request a fresh OTP afterwards (Redis state not carried over).
- Push notifications pause and resume; batched ones fire on the next scheduler tick.

## AFTER (this week)
- Nightly `pg_dump` cron on the EC2 → S3/R2 (RDS snapshots don't cover app-level deletes).
- Day 7: final Neon snapshot → decommission project; rotate old Neon + Upstash creds out of
  all secrets; delete `.env.neon-backup-*`.
- Re-run the §2 latency table from PERF_PROFILE_v1.0.17.md and file before/after numbers.

**Go/no-go gates:** step 5 (≤5 ms) · step 12 (`ALL CHECKS PASS`) · step 15 (health 200) ·
step 17 smoke. Fail any ⇒ Phase C, retry another night. No improvisation mid-window.

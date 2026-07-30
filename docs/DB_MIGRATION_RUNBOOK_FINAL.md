# DB MIGRATION RUNBOOK — Neon (Singapore) → RDS PostgreSQL ap-south-1 (same VPC as EC2) + local Redis

**Final numbered runbook for tomorrow night. Target decided by user: RDS ap-south-1 in the
EC2's VPC; Redis moves to a local instance on the EC2 box.**
Downtime budget: 10–15 min. Copy itself <1 min (DB is 11 MB). Roll back = env flip, 3–5 min.

Verification is scripted: `backend/scripts/verify_migration.py` (run in rehearsal AND at cutover).

---

## PHASE 0 — Prerequisites (tonight / tomorrow daytime, no downtime)

1. Confirm EC2 region/AZ: `curl -s http://169.254.169.254/latest/meta-data/placement/availability-zone`
   → must be ap-south-1x. (Co-location with the backend is the entire point.)
2. Provision RDS PostgreSQL:
   - Engine **PostgreSQL 17 or 18** (source is 18.4; ≥17 restores our plain dump fine).
   - Instance: `db.t4g.micro` is enough (11 MB DB, ~400 employees); enable storage autoscaling.
   - **Same VPC as the EC2**, private subnet, NO public access.
   - Security group: inbound 5432 from the EC2's security group only.
   - Automated backups ON (7 days), deletion protection ON.
3. On RDS, create DB + extension:
   ```sql
   CREATE DATABASE hogoplus;
   \c hogoplus
   CREATE EXTENSION IF NOT EXISTS vector;   -- MUST succeed (Sahayak RAG)
   ```
4. Local Redis on the EC2:
   ```bash
   sudo apt install -y redis-server
   # /etc/redis/redis.conf: bind 127.0.0.1 ::1 ; appendonly yes
   sudo systemctl enable --now redis-server && redis-cli ping   # PONG
   ```
   Redis holds only OTP state, rate-limit counters, sweep locks and batch keys —
   all self-expiring. NOTHING needs to be copied from Upstash; users mid-OTP during
   the window simply request a new OTP.
5. Latency proof from the EC2 (record the numbers):
   ```bash
   python3 - <<'EOF'
   import time, psycopg2
   c = psycopg2.connect("<RDS_URL>")
   cur = c.cursor()
   for _ in range(3):
       t0=time.time(); cur.execute("SELECT 1"); cur.fetchone()
       print(f"{(time.time()-t0)*1000:.1f} ms")
   EOF
   ```
   Target ≤ 5 ms (vs 217 ms today). If >20 ms, stop and check VPC routing.

## PHASE 1 — Rehearsal (tomorrow daytime, no downtime)

6. Dump from Neon (from the EC2):
   `pg_dump "<NEON_URL>" --no-owner --no-privileges -Fc -f /tmp/hogo_rehearsal.dump`
7. Restore into RDS:
   `pg_restore --no-owner --clean --if-exists -d "<RDS_URL>" /tmp/hogo_rehearsal.dump && psql "<RDS_URL>" -c "ANALYZE"`
8. Scripted verification:
   `cd /app/backend && SOURCE_URL="<NEON_URL>" TARGET_URL="<RDS_URL>" python scripts/verify_migration.py`
   → must print `ALL CHECKS PASS`.
9. Point a STAGING copy of the backend at RDS + local Redis and run:
   `DATABASE_URL=<RDS_asyncpg_URL> REDIS_URL=redis://127.0.0.1:6379/0 python -m pytest tests/ -q`
   (218+ tests) and `alembic current` → must equal `0013 (head)`.
10. Fix any surprises NOW. Do not proceed to Phase 2 with a dirty rehearsal.

## PHASE 2 — Cutover (tomorrow night, downtime window; suggested 23:30 IST after C-shift punch-ins settle)

11. Announce in-app 30 min ahead (📣 Announce, trilingual: "app will pause ~15 min at 23:30").
12. T-0: stop writes — on the EC2: `sudo systemctl stop hogo-celery hogo-celerybeat` then stop
    (or 503) the API service. Confirm no active connections:
    `psql "<NEON_URL>" -c "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid();"` → 0.
13. Final dump + restore (repeat steps 6–7 with a fresh `/tmp/hogo_final.dump`).
14. Verification: rerun step 8 against the final restore → `ALL CHECKS PASS` required.
15. Flip env on the EC2 (`/etc/hogo/backend.env` or equivalent):
    - `DATABASE_URL=postgresql+asyncpg://…rds…ap-south-1…/hogoplus?ssl=require`
    - `REDIS_URL=redis://127.0.0.1:6379/0` (+ Celery broker/result URLs if separate)
16. Start services: API, celery worker, celery beat. `curl localhost:8001/api/health` → healthy.
17. Neon: revoke writes (keep it online as rollback anchor):
    `ALTER DATABASE <db> SET default_transaction_read_only = on;`
18. Smoke (5 min, demo bubble — no SMS): D500 OTP login → home loads · one demo punch-in →
    zone resolves · one demo vehicle log → appears in register · webdash login → Vehicle
    Register renders · `alembic current` = 0013.
19. Latency after: re-run step 5 probe + hit `/api/incidents` with a token — expect
    p50 < 400 ms (was 2.7 s). Save numbers for the before/after perf report.
20. Close the window; watch logs for 60 min (`journalctl -fu hogo-api`).

## PHASE 3 — Rollback (only if step 14/16/18 fails)

R1. Stop API + Celery.
R2. Neon: `ALTER DATABASE <db> SET default_transaction_read_only = off;`
R3. Revert `DATABASE_URL` (and `REDIS_URL` if Redis is implicated — Upstash unchanged).
R4. Start services, rerun step 18 smoke. Total ≈ 3–5 min.
R5. If real writes landed on RDS before rollback, replay them from RDS `audit_events`
    (every mutation is audited) before re-opening; with the recommended window there
    should be none.

## PHASE 4 — Post-cutover (this week)

21. Nightly `pg_dump` cron on the EC2 to S3/R2 (RDS snapshots alone don't cover
    accidental-deletion-by-app scenarios).
22. After 7 clean days: final Neon snapshot → decommission project; rotate the old
    connection string + Upstash creds out of all secrets/CI.
23. Re-run the §2 latency table from PERF_PROFILE_v1.0.17.md and file the
    before/after numbers.

**Cutover decision points:** step 5 (≤5 ms), step 8/14 (`ALL CHECKS PASS`), step 18 smoke.
Fail any → rollback, investigate, retry another night. No improvisation mid-window.

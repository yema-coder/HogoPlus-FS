# Backup → Restore Drill (RDS, production) — prove backups work end to end

**Why now:** the fork of 2026-07-30 found and fixed a real DR bug — `restore_latest.py`
crashed (exit 3) on the data-only Python-fallback dumps that production actually
produces (prod containers ship without `pg_dump`). The fix: the script now detects
data-only dumps, runs `alembic upgrade head` against the TARGET db first, and skips
the dump's own `alembic_version` row. A full drill was executed in the sandbox on
2026-07-30 (backup `backups/2026-07-31/0030.sql.gz` → scratch db): 447 employees,
17 incidents, 18 attendance, 7 vehicle logs, 40 notifications, 493 audit events,
schema stamped 0014. This document is the SAME drill for your EC2 + RDS.

**Facts to know first**
- The backup job dumps whatever `DATABASE_URL` the API process runs with
  (`app/tasks.py: run_backup_sync` → `settings.database_url`). There is **no Neon
  reference anywhere in code** — if `/opt/hogoplus/.env` points at RDS, backups ARE
  from RDS.
- Schedule: every 4h (IST clock), uploaded to R2 `backups/YYYY-MM-DD/HHMM.sql.gz`.
  Retention: last 48h of intraday + the 00:30 daily for 14 days.
- Prod dumps use the Python fallback (data-only INSERTs) — restorable ONLY with the
  fixed script (`backend/scripts/restore_latest.py`), which is what this drill proves.
- `--target <scratch-db>` is what keeps the drill safe. NEVER run `--yes` without
  `--target` against production.

---

## The drill (run on the EC2 host, ~10 minutes)

1. **Confirm backups come from RDS, not Neon:**
   ```bash
   grep '^DATABASE_URL' /opt/hogoplus/.env
   ```
   ✅ Host must be your `*.rds.amazonaws.com` endpoint. If you still see
   `*.neon.tech`, STOP — fix the env and restart the stack first.

2. **Confirm the backup job is actually producing fresh dumps:**
   ```bash
   docker compose -f /opt/hogoplus/docker-compose.yml logs api 2>&1 \
     | grep "Uploaded DB backup" | tail -3
   ```
   ✅ Newest line should be < 4 hours old, e.g.
   `Uploaded DB backup to backups/2026-06-XX/1130.sql.gz (method=python, NNNN bytes gz)`.
   (`method=python` is expected — prod has no pg_dump.)

3. **Give the api container a psql client (ephemeral — gone on next deploy):**
   ```bash
   docker compose -f /opt/hogoplus/docker-compose.yml exec api \
     bash -lc "apt-get update -qq && apt-get install -y -qq postgresql-client"
   ```

4. **Dry-run (shows which backup would be restored, changes nothing):**
   ```bash
   docker compose -f /opt/hogoplus/docker-compose.yml exec api \
     python scripts/restore_latest.py --latest
   ```

5. **REAL restore into a scratch database on the same RDS instance:**
   ```bash
   docker compose -f /opt/hogoplus/docker-compose.yml exec api \
     python scripts/restore_latest.py --latest --yes --target hogoplus_drill
   ```
   Expected output ends with:
   `RESTORE COMPLETE into 'hogoplus_drill' — employees | public tables:  <N> | <M>`
   (The script itself: recreates `hogoplus_drill`, `CREATE EXTENSION vector`,
   `alembic upgrade head` on the scratch db, applies the dump minus its
   alembic_version row.)

6. **Validate the restored data against the LIVE database:**
   ```bash
   docker compose -f /opt/hogoplus/docker-compose.yml exec api python - << 'EOF'
   import asyncio, asyncpg, re
   from app.config import settings

   async def counts(db):
       url = re.sub(r"/[^/?]+$", f"/{db}", settings.database_url.replace("+asyncpg", ""))
       c = await asyncpg.connect(url)
       out = {t: await c.fetchval(f"SELECT count(*) FROM {t}")
              for t in ("employees", "incidents", "attendance", "vehicle_logs", "notifications")}
       out["alembic"] = await c.fetchval("SELECT version_num FROM alembic_version")
       await c.close()
       return out

   live = asyncio.run(counts("hogoplus"))
   drill = asyncio.run(counts("hogoplus_drill"))
   print(f"{'table':20} {'live':>8} {'drill':>8}")
   for k in live:
       print(f"{k:20} {str(live[k]):>8} {str(drill[k]):>8}")
   EOF
   ```
   ✅ Drill counts must equal live counts minus anything written since the backup
   timestamp (a few rows drift is normal on a live system).
   ✅ `alembic` must show the SAME revision on both.

7. **Spot-check one real record** (proves data integrity, not just counts):
   ```bash
   docker compose -f /opt/hogoplus/docker-compose.yml exec api bash -lc \
     'psql "$(python -c "from app.config import settings; import re; \
   print(re.sub(r\"/[^/?]+$\", \"/hogoplus_drill\", settings.database_url.replace(\"+asyncpg\",\"\")))")" \
     -c "SELECT emp_id, full_name, dept_code, is_approved FROM employees ORDER BY created_at DESC LIMIT 3"'
   ```
   ✅ Should show your most recently registered employees with correct names.

8. **Clean up — drop the scratch database:**
   ```bash
   docker compose -f /opt/hogoplus/docker-compose.yml exec api bash -lc \
     'psql "$(python -c "from app.config import settings; import re; \
   print(re.sub(r\"/[^/?]+$\", \"/postgres\", settings.database_url.replace(\"+asyncpg\",\"\")))")" \
     -c "DROP DATABASE IF EXISTS hogoplus_drill WITH (FORCE)"'
   ```

9. **Record the drill** (so "backups work" has a date on it): note in your ops log —
   date, backup key restored, row counts compared, PASS/FAIL. Repeat quarterly and
   after every schema migration.

## If any step fails
- Step 2 no fresh backups → check `FILE_STORAGE_MODE=s3` and R2 credentials in
  `/opt/hogoplus/.env`; backup silently skips in local mode (by design).
- Step 5 `CREATE DATABASE` permission error → your RDS user isn't the master user;
  either use the master credentials for the drill or pre-create `hogoplus_drill`
  manually and re-run.
- Step 5 `CREATE EXTENSION vector` fails → RDS PG version must have pgvector
  (PG15+); it already works on live, so this only fails if the drill runs on a
  different instance.
- Anything else → the restore script prints the failing SQL context; send it to the
  agent with the backup key name.

## Optional hardening (recommended, not urgent)
- Add `postgresql-client-16` to the prod API image → backups switch from the
  data-only Python fallback to full `pg_dump` (schema+data, single-file restore).
- RDS automated snapshots are ALREADY your first net (point-in-time recovery);
  this R2 dump is the portable second net that also covers "RDS account lost".

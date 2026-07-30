# DB Migration Plan — Neon (Singapore) → Mumbai-region Postgres

**Status: WRITTEN PLAN ONLY — no execution until approved.**
Prepared 2026-06 for HogoPlus-FS. Driver: measured 217 ms per DB query from the
backend (cross-region), the #1 performance item from PERF_PROFILE_v1.0.17.md.

---

## 0. Pre-flight — confirm the backend's region FIRST (critical)

Co-location with the **backend** is the whole point; proximity to users is irrelevant
for DB latency (users touch the API once per request, the backend touches the DB
4–12 times per request).

1. From the PRODUCTION backend (api.hogoplus.in host), run a latency probe to
   candidate regions (simple `SELECT 1` against trial instances, or TCP ping to
   region endpoints).
2. Pick the DB region with the lowest RTT **from the backend**, even if that is not
   literally Mumbai. If the backend runs in the US, a Mumbai DB will be as bad as
   Singapore — in that case the correct move is either (a) move the backend deploy
   region too, or (b) choose the DB region closest to the backend.
3. Target: **≤ 5 ms RTT** backend→DB (same region/AZ family). That turns the
   measured 2.7 s /incidents into ~50–150 ms with zero code changes.

## 1. Current state (measured)

| Item | Value |
|---|---|
| Source | Neon, `ep-late-sea-aopqk5ht-pooler`, aws ap-southeast-1 (Singapore) |
| Postgres version | **18.4** |
| DB size | **11 MB** (tiny — dump/restore takes seconds) |
| Extensions | `plpgsql`, **`vector` (pgvector)** — target MUST support pgvector |
| Largest tables | audit_events 471, shift_assignments 448, employees 446 rows |
| Writers | FastAPI backend, Celery worker + beat (scheduler), webdash via same API |
| Redis (Upstash) | ALSO cross-region at 215 ms/op — migrate/replace in the same window |

## 2. Target options (Mumbai / aws ap-south-1)

Neon does **not** currently offer a Mumbai region (nearest: Singapore — where we
already are), so a Mumbai move means changing provider:

| Option | Region | pgvector | PG ≥ 17/18 | Notes |
|---|---|---|---|---|
| **Supabase (managed PG)** | aws ap-south-1 Mumbai | ✅ | ✅ | Closest DX to Neon; pooler included (Supavisor) |
| AWS RDS / Aurora PostgreSQL | ap-south-1 | ✅ | ✅ | Most control; needs VPC/public-access config; higher ops overhead |
| GCP Cloud SQL | asia-south1 Mumbai | ✅ | ✅ | Fine if rest of infra ever moves to GCP |
| Azure Flexible Server | Central India Pune | ✅ | ✅ | Pune ≈ Mumbai latency |

Version note: source is PG 18.4. Prefer a target on PG ≥ 17 and restore via plain
SQL dump (works across majors); verify `CREATE EXTENSION vector` before import.

Redis: replace Upstash endpoint with a Mumbai-region Redis (Upstash has ap-south-1)
in the same cutover — OTP flow does 2–4 Redis ops per request today.

## 3. Cutover strategy — chosen approach: dump/restore in a maintenance window

With an 11 MB database, logical replication machinery is overkill. A short
maintenance window is simpler, safer and fully rehearsable.

**Estimated downtime: 10–15 minutes** (rehearsed), of which the actual data copy is
< 1 minute; the rest is verification. Schedule between shifts (e.g., 14:30 IST after
A-shift punch-outs settle) to avoid attendance punches.

### Steps

1. **T-2 days — rehearsal (no downtime):** create the target instance, enable
   `vector` extension, restore a fresh dump, run the verification suite (§5), point a
   STAGING backend at it and run `pytest` (218 tests) + `scripts/selfreg_e2e.py`.
   Fix any surprises now.
2. **T-0 (window opens):** put the API into maintenance mode — return 503 with a
   trilingual "back in a few minutes" from the ingress or a `MAINTENANCE=true` env
   flag. Stop Celery worker + beat (prevents mid-copy writes).
3. Take the final dump: `pg_dump --no-owner --no-privileges -Fc` from Neon.
4. Restore into the Mumbai target: `pg_restore --no-owner -d <target>`; run
   `ANALYZE`.
5. Run the data-integrity verification (§5) — scripted, ~2 minutes.
6. Flip `DATABASE_URL` (+ `REDIS_URL`/`CELERY_*` if migrating Redis) in Deployment
   Secrets; redeploy backend; restart Celery.
7. Smoke: `/api/health`, OTP login (dedicated test account D500), one punch-in on a
   test account, webdash login, one incident read.
8. Close window. Keep Neon **read-only** (revoke writes) but ONLINE for 7 days as
   the rollback anchor, then decommission.

### Alembic
`alembic_version` travels with the dump — no re-stamping needed. Confirm
`alembic current` on the target matches head after cutover.

## 4. Rollback

- **Trigger:** any §5 check fails, or smoke tests fail, or errors within the first
  hour post-cutover that trace to the DB.
- **Action:** flip `DATABASE_URL` back to Neon (unrevoke writes), redeploy backend,
  restart Celery. Rollback time ≈ 3–5 minutes (one env flip + redeploy).
- **Data-loss window on rollback:** only writes made to Mumbai between cutover and
  rollback. Mitigation: keep the maintenance window short and do the first-hour
  observation during a low-traffic period; if rollback happens after real writes,
  replay them from `audit_events` on the Mumbai side (every mutating action is
  audited) before re-opening.

## 5. Data-integrity verification (scripted, run in rehearsal AND at cutover)

1. **Row counts** per table (all ~30 tables): source vs target must match exactly.
2. **Checksums:** `md5(string_agg(...))` over ordered primary keys + critical columns
   for employees (id, emp_id, phone, onboarding_status), attendance, incidents,
   shift_assignments, ble_beacons.
3. **Sequences/identity:** next values ≥ source (prevents PK collisions).
4. **pgvector:** `SELECT COUNT(*) FROM <embedding tables> WHERE embedding IS NOT NULL`
   matches, and one similarity query returns identical top-3 ids (Sahayak RAG).
5. **Constraints/indexes:** compare `pg_indexes` and FK lists source vs target.
6. **Functional:** login (demo cast), punch-in + zone resolve, incident create/read,
   form submit, approval queue read — on the staging backend against the target.
7. **Latency proof:** `SELECT 1` RTT from production backend ≤ 5 ms (the entire
   point of the exercise) — record before/after numbers for the perf report.

## 6. Post-cutover follow-ups

- Re-run the §2 latency table from PERF_PROFILE_v1.0.17.md and publish before/after.
- Update backup jobs (`/api/admin/backup-now` target, nightly PDF cron unaffected).
- Rotate the old Neon connection string out of all secrets after decommission.

**Approval needed on:** target provider (recommend Supabase ap-south-1 unless the
backend region probe says otherwise), Redis migration in the same window (recommend
yes), and the maintenance-window date/time.

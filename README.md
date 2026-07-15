# Hogo Plus-FS — Factory Operations Platform

Trilingual (English / हिंदी / मराठी) factory operations suite for a sugar factory:

- **Mobile app** (`/app/frontend`, Expo + React Native): OTP login, geofenced + BLE + face-verified attendance, department forms with AI hooks (ANPR, gauge reading, voice-fill), incident reporting, shift swaps, Sahayak SOP chat.
- **Backend** (`/app/backend`, FastAPI + PostgreSQL 16 + pgvector + Redis + Celery): all APIs under `/api`, AI services via the Emergent LLM key, files on Cloudflare R2, face verification via AWS Rekognition.
- **MD Command Center** (`/app/webdash`, React + Vite): desktop web dashboard for Manager / CGM / MD, served by FastAPI at **`/api/dash/`**. Managers see only their own department (enforced server-side); CGM/MD see all 13 departments.

## MD Command Center (web)

- URL: `https://<your-domain>/api/dash/`
- Login: same phone + OTP auth as mobile. Restricted to Manager rank and above.
- Screens: Overview (KPIs, department health, live incidents), Department drill-down (14-day trends, attendance register, submissions, incidents), Approvals aging (by manager, escalations), Attendance register (flagged punch approve/reject for Time Office / CGM / MD), Reports & AI (daily PDF reports, AI usage, Sahayak chat), Admin (geofence, assign managers, fix missing phones, change roles, SOP PDFs, manual backup).
- Rebuild after changes: `cd /app/webdash && yarn build` (outputs to `/app/backend/webdash_dist`), then restart the backend.

## Backups

- Celery beat runs `pg_dump` **every 4 hours** and uploads gzipped dumps to R2 under `backups/YYYY-MM-DD/HHMM.sql.gz` (30-day retention).
- Manual backup: `POST /api/admin/backup-now` (CGM/MD) or the **Backup now** button in the web Admin screen.
- On startup the backend checks the `employees` table. If it is empty it logs `CRITICAL`, sets `/api/health` → `db_seeded: false`, and notifies the CGM. **It never auto-restores.**

## DISASTER RECOVERY

If the database is empty / lost (`/api/health` shows `"db_seeded": false`):

```bash
cd /app/backend
python scripts/restore_latest.py                 # 1. list available backups (newest first)
python scripts/restore_latest.py --latest --yes  # 2. restore the newest backup + alembic upgrade head
# or a specific one:
python scripts/restore_latest.py --key backups/2026-07-14/0030.sql.gz --yes
# optional scratch-DB drill (does NOT touch the live DB):
python scripts/restore_latest.py --latest --yes --target hogoplus_drill
```

The script drops + recreates the target DB, installs pgvector, restores the dump, runs
`alembic upgrade head` (live DB only) and prints the employee count as verification
(expect **401** employees). Afterwards: `sudo supervisorctl restart backend celery_worker celery_beat`
and confirm `/api/health` shows `"db_seeded": true`.

If PostgreSQL itself is missing (fresh machine): install `postgresql-16` + `postgresql-16-pgvector`,
create the role and DB from `DATABASE_URL` (`CREATE ROLE hogo LOGIN PASSWORD '…' SUPERUSER; CREATE DATABASE hogoplus OWNER hogo;`),
then run the restore script.

> **Deployment reminder:** all secrets (DATABASE_URL, JWT_SECRET, R2 keys, AWS Rekognition keys,
> EMERGENT_LLM_KEY, MSG91 keys) must be added in **Deployment → Secrets** — never hardcode them.

## LAUNCH DAY RUNBOOK (do these in order)

1. **Deploy** the app (Publish button) and wait for it to go live.
2. **Add all secrets** in Deployment → Secrets: `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `JWT_SECRET`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET`, `FILE_STORAGE_MODE=s3`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `EMERGENT_LLM_KEY`, `SMSGATEWAYHUB_API_KEY`, `SMSGATEWAYHUB_SENDER_ID`, `SMSGATEWAYHUB_DLT_TEMPLATE_ID`, `OTP_TEMPLATE_TEXT`, `OTP_MODE=smsgatewayhub`, `DEMO_OTP_ENABLED=false`. Before flipping `OTP_MODE`, verify real delivery with `POST /api/admin/test-sms {"phone": "+91…"}` (CGM only) — it returns the provider's raw response.
3. **Verify health**: open `https://<domain>/api/health` → must show `"db_seeded": true`. If false, run the DISASTER RECOVERY steps above first.
4. **Set the geofence**: log in to `https://<domain>/api/dash/` as CGM → Admin → Factory geofence → enter the real factory latitude / longitude / radius → Save.
5. **Assign the 7 department managers** (ACCOUNTS, AGRICULTURE, CANE_YARD, CIVIL, DISTILLERY, GODOWN, STORE currently route to CGM): Admin → Assign department manager → pick department → search employee → Assign.
6. **Fix the 6 pending phone numbers** (emp 0139, 0403, 0470, 0914, 0949, 1211): Admin → Employees without phone → enter phone → Save. Each becomes `approved` and can log in.
7. **Create the MD account**: Admin → Change employee role → search the MD's employee record → set role **MD** → Apply. (Until then, escalations stop at CGM by design.)
8. **Upload SOP PDFs**: Admin → SOP documents → Upload PDF. Wait for status **ready** — Sahayak chat answers only from ready documents.

## Development

- Backend tests: `cd /app/backend && python -m pytest tests/ -q` (111 tests).
- Services: `sudo supervisorctl status` — backend (8001), expo (3000), postgresql, redis, celery_worker, celery_beat.
- Demo OTP: `123456` (only for phones already in the employees table; disable in production via `DEMO_OTP_ENABLED=false`).

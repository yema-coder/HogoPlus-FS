# Hogo Plus-FS — Backend (Phase 1 of 4)

Factory management platform backend for **Prasad Sugar & Allied Agro Products Ltd**.
Single system of record: phone+OTP auth, dynamic Form Engine, 3-tap incident reporting
with escalation, GPS+selfie attendance, shift management with swaps, audit logging,
file uploads, notifications foundation.

## Stack
- FastAPI + SQLAlchemy 2.0 (async) + Alembic + Pydantic v2
- PostgreSQL 16 with **pgvector** enabled (vector features arrive in a later phase)
- Redis 7 (OTP store, rate limiting, Celery broker)
- Celery worker + beat (escalation sweeps every 30 min, nightly 02:30 IST DB backup)
- JWT HS256 (access 24h, refresh 30d) via python-jose

## Run
```bash
cd backend
cp .env.example .env            # fill JWT_SECRET, DATABASE_URL
pip install -r requirements.txt
alembic upgrade head            # migration 0001 (creates pgvector extension + all tables)
python scripts/generate_seed_csv.py   # only if seed_employees.csv is missing
python seed.py                  # idempotent — safe to re-run
uvicorn server:app --host 0.0.0.0 --port 8001
celery -A app.celery_app.celery worker --loglevel=INFO
celery -A app.celery_app.celery beat --loglevel=INFO
```
In this environment all six processes (backend, postgresql, redis, celery_worker,
celery_beat, expo) run under supervisor: `sudo supervisorctl status`.

## Tests
```bash
cd backend && python -m pytest tests/ -q     # 66 tests, PostgreSQL 16 + Redis required
```

## Auth flow
1. `POST /api/auth/send-otp {phone}` — +91 format, 3 per 10 min per phone. OTP hashed (SHA256) in Redis, 5-min TTL. Delivery pluggable via `OTP_MODE`: `demo` (logs OTP; `DEMO_OTP=123456` accepted when `DEMO_OTP_ENABLED=true`) | `msg91` (stub, raises NotConfigured until keys provided) | `whatsapp` (stub).
2. `POST /api/auth/verify-otp {phone, otp}` — 5 wrong = 30-min lockout. Known phone → JWT pair + profile. Unknown phone → `{is_new: true}` (phone marked OTP-verified for 15 min so `/auth/register` can be called).
3. `POST /api/auth/register` — creates Worker with `pending_approval`; restricted to incident creation, own profile, department list until approved via `POST /api/admin/employees/{id}/approve`.
4. `GET /api/auth/me`, `POST /api/auth/refresh`, `PATCH /api/employees/me`.

Roles (rank): MD(1), CGM(2), Manager(3), Staff(4), Clerk(5), Worker(6). `require_role(min_rank)` guards admin/approval endpoints; CGM/MD read everything.

## Key endpoints (all under `/api`)
- Forms: `GET /forms`, `POST /forms/{id}/submit`, `POST /submissions/{id}/approve|reject`, `GET /submissions` (paginated, role-scoped), admin `POST/PATCH /admin/forms` (schema edit bumps version).
- Incidents: `POST /incidents` (auto-assign dept Manager, CGM fallback), `GET /incidents/mine|/{id}|`, `POST /incidents/{id}/status`. Escalation sweep every 30 min: pending > `ESCALATION_HOURS` → CGM → MD (stays with CGM while no MD exists).
- Attendance: `POST /attendance/punch-in` (geofence+beacon → verified_plus / verified / flagged; C-shift punches before 06:00 attribute to previous day; 15-min grace for lateness; duplicate = 409), `punch-out`, `GET /attendance/mine|department/{code}|flagged`, `POST /attendance/{id}/approve`, `GET /dashboard/attendance-summary`.
- Shifts: `GET /shifts/mine|roster`, swaps `POST /shift-swaps` → target `respond` → manager `decide` (same dept, both eligible, different shifts; swap applies to that date only; both sides audited).
- Files: `POST /files/upload` (10 MB; jpeg/png/webp/m4a/mp3/pdf), `GET /files/{key}`. `FILE_STORAGE_MODE=local|s3` (R2 presigned 24h).
- Admin: settings geofence (CGM/MD), employees patch/approve (Time Office/CGM/MD), assign-manager (CGM/MD), beacons CRUD. All mutations audited.
- Notifications: `GET /notifications/mine`, `POST /notifications/{id}/read` (trilingual rows; Expo push wired in mobile phase via NoopPushSender).

## Seed data
`seed_employees.csv` — 401 rows (synthetic; regenerate with `scripts/generate_seed_csv.py`,
replace with real mill CSV anytime — `seed.py` is idempotent). CGM = emp 0001. 6 departments
have Managers (PRODUCTION, ENGINEERING, SECURITY, TIME_OFFICE, ACCOUNTS, STORE); the other 7
route approvals to CGM until `assign-manager` is called. 6 rows with `phone_status != OK`
seeded with `phone=NULL`, `onboarding_status='seeded'` — fix via `PATCH /api/admin/employees/{id}`.
No MD in seed data — create later via admin endpoints; escalations stay with CGM meanwhile.
Workers in ENGINEERING/PRODUCTION/SECURITY/DISTILLERY/CANE_YARD → shift A; everyone else GEN.
13 trilingual starter form definitions (one per department). Settings row: 19.0000/74.7000, 500 m.

## Notes / deviations
- All routes are prefixed `/api` (Kubernetes ingress requirement of this environment).
- `DEMO_OTP` is accepted for **any** phone (not just seeded ones) while `DEMO_OTP_ENABLED=true`, so the self-registration flow can be demoed end-to-end. Set `DEMO_OTP_ENABLED=false` in production.
- `POST /files/upload` is unauthenticated in this phase because the registration selfie is uploaded before a JWT exists; keys are unguessable UUIDs.

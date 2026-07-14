# Hogo Plus-FS — PRD / Memory

## Original problem statement
Build Phase 1 of 4 (BACKEND ONLY) of Hogo Plus-FS — a factory management platform for
Prasad Sugar & Allied Agro Products Ltd (sugar mill, Maharashtra). ~400 employees scaling
to 5,000, semi-literate users, trilingual (en/hi/mr, Marathi default). Backend is the single
system of record. Locked stack: FastAPI + SQLAlchemy 2.0 async + Alembic + Pydantic v2,
PostgreSQL 16 + pgvector, Redis 7, Celery worker+beat, JWT HS256 (24h/30d), pytest ≥ 40 tests.
FORBIDDEN: MongoDB, Firebase, Supabase, GraphQL, Prisma, payment gateways, "Supervisor" as role name.
Phases 2–4 (later): mobile app (Expo, trilingual), AI hooks (gauge_read/anpr/headcount), vector features.

## User choices (2026-07-14)
- seed_employees.csv was NOT attached → agent generated synthetic 401-row CSV (replaceable; seed idempotent)
- All routes under `/api` prefix (ingress requirement) — approved
- C-shift punches before 06:00 attribute to previous day — approved
- Department managers auto-assigned from seed designations (6 assigned, 7 left NULL) — approved

## User personas
- Worker (semi-literate, Marathi): punch attendance, report incidents, submit forms, swap shifts
- Manager: approve submissions/swaps/registrations, incident triage, dept attendance
- Time Office Manager: flagged attendance approval, employee record fixes
- CGM (emp 0001): top of escalation until MD account is created; sees everything
- MD: dashboard (later phase)

## Architecture (implemented 2026-07-14)
- /app/backend/app: config, database (async engine), models (16 tables, UUID PKs), security (JWT+RBAC),
  otp (DemoSender/MSG91Sender/WhatsAppSender stubs), storage (Local/S3 adapters), notify (dispatcher + NoopPushSender),
  escalation, celery_app + tasks, form_validation, shift_logic, routers (auth, departments, forms,
  incidents, attendance, shifts, files, admin, notifications)
- Alembic migration 0001 (creates pgvector extension + all tables); seed.py idempotent
- Supervisor: backend(8001), postgresql(16.14), redis(7.0.15), celery_worker, celery_beat
- Celery beat: escalation sweep */30min; nightly pg_dump backup 21:00 UTC (=02:30 IST), skips when FILE_STORAGE_MODE=local
- DBs: hogoplus (dev, seeded), hogoplus_test (pytest). Postgres user hogo/hogo_secret (superuser, dev)

## What's been implemented (2026-07-14) — Phase 1 complete
- Auth: send-otp (rate limit 3/10min), verify-otp (5 wrong → 30min lockout, demo OTP 123456),
  register (pending_approval Worker, restricted middleware), refresh, me, PATCH /employees/me
- Form Engine: dept-scoped list, schema validation (all field types + min/max/regex), submit → manager
  notification, approve/reject + audit, paginated role-scoped list, admin CRUD with version bump
- Incidents: create (auto-assign dept manager → CGM fallback), mine/detail(+timeline)/list (role-scoped),
  status changes (timeline+audit+notify), escalation sweep (→CGM→MD, graceful no-MD handling)
- Attendance: punch-in (verified_plus/verified/flagged, geofence haversine vs settings row,
  C-shift previous-day attribution, 15-min grace lateness, 409 duplicates), punch-out, mine/department/
  flagged lists, Time Office approval, dashboard summary
- Shifts: mine (8 days), roster, swap full flow (eligibility rules, date-only override assignments, both-sides audit)
- Files: upload (10MB, type whitelist) + serve; local/s3 adapter; Admin: settings/employees/assign-manager/beacons
- Notifications: trilingual rows + read; audit_events on all specified actions
- Tests: **66 passing** (pytest, PG16 + Redis)

## Deviations (justified)
1. `/api` prefix on all routes (environment ingress requirement)
2. DEMO_OTP accepted for any phone (not just seeded) so registration flow is demoable; disable via DEMO_OTP_ENABLED=false
3. `POST /files/upload` unauthenticated (registration selfie precedes JWT); UUID keys
4. Synthetic seed CSV (real one wasn't attached); format documented, seed idempotent for replacement

## Backlog / next phases
- P0 (Phase 2): Expo mobile app — trilingual UI (mr default), OTP login, 3-tap incident, punch-in with
  camera selfie + GPS, forms renderer from schema_json, manager approval screens
- P1: MSG91 OTP wiring (needs MSG91_AUTH_KEY), Cloudflare R2 creds, real factory geofence coords,
  MD account creation, Expo push delivery (replace NoopPushSender)
- P2: AI hooks (gauge_read, anpr, headcount), pgvector features, BLE beacon enrollment UX

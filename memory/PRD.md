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

## What's been implemented (2026-07-14) — Phase 1 complete + Fix Pack 1
### Fix Pack 1 (2026-07-14, after Phase 1 finish)
- FIX 1: Real seed_employees.csv (401 rows) replaced synthetic data. DB employees/assignments wiped and reseeded.
  CGM = Amey Ghadge 0001 (+918483029039). 6 dept managers: ADMIN 0704, ENGINEERING 0146 (Mhaske Sanjay,
  Works Manager — lowest-emp_id rule), PRODUCTION 0351, PURCHASE 0046, SECURITY 0429, TIME_OFFICE 0008.
  7 without: ACCOUNTS, AGRICULTURE, CANE_YARD, CIVIL, DISTILLERY, GODOWN, STORE. 6 phone-NULL 'seeded' rows
  (0139, 0403, 0470, 0914, 0949, 1211). seed.py adapted to real CSV columns (name/role/YES-NO eligibility).
  scripts/generate_seed_csv.py deleted — repo CSV IS the real file.
- FIX 2: DEMO_OTP only accepted for phones existing in employees table; unknown phones need the real
  (logged) OTP; static 123456 can never create accounts. Test added.
- FIX 3: verify-otp for unknown phone returns {is_new, registration_token} (JWT 15-min, scope=registration).
  /files/upload + /auth/register require access OR registration token (401 otherwise); magic-byte content
  validation; upload rate limit 20/hour per token (Redis). Tests added.
- Test suite now **70 passing**.

### Phase 1 (original)
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
2. ~~Synthetic seed CSV~~ → replaced with real 401-row CSV in Fix Pack 1
3. ~~DEMO_OTP for any phone~~ → hardened in Fix Pack 1 (seeded phones only)
4. ~~Unauthenticated upload~~ → secured in Fix Pack 1 (access/registration token + magic bytes + 20/hr rate limit)

## Backlog / next phases
- P0 (Phase 2): Expo mobile app — trilingual UI (mr default), OTP login, 3-tap incident, punch-in with
  camera selfie + GPS, forms renderer from schema_json, manager approval screens
- P1: MSG91 OTP wiring (needs MSG91_AUTH_KEY), Cloudflare R2 creds, real factory geofence coords,
  MD account creation, Expo push delivery (replace NoopPushSender)
- P2: AI hooks (gauge_read, anpr, headcount), pgvector features, BLE beacon enrollment UX

## Phase 2 Part 1 — Mobile App (completed 2026-06, fork session)
Expo SDK 54 + Expo Router v6, TypeScript strict, Zustand, react-i18next (en/hi/mr, mr default),
Baloo 2 loaded via expo-font (raw .ttf in assets/fonts — no fonttools needed; earlier failure was
just stale Metro cache). i18n parity: 176 keys × 3 languages, script passes.

### Implemented & tested
- Auth: language → phone → OTP (auto-submit at 6 digits) → home; unknown phone → register
  (name → department FROM GET /api/departments, 13 trilingual entries → selfie → pending w/ polling).
- Tabs: Home / Reports / Alerts (unread badge) / Profile. Role-aware: rank≤3 gets Approvals tile
  (coming-soon toast) + Mine/Department toggle on Reports.
- Home: red incident tile (P0), attendance card (not-punched → punch-in / on-duty → punch-out w/
  confirm modal / day-complete), today-shift chip, grid tiles.
- Incident 3-tap: category grid → back camera + contextual GPS (chip: searching/ok/none/blocked→settings)
  → preview with watermark overlay (HOGO PLUS · category · timestamp · GPS · name/emp_id) burned in via
  react-native-view-shot captureRef (max dim 1600, compress 0.7 → ~300-500KB; web falls back to plain
  compressed photo) → dept selector modal + optional description → SUBMIT. Offline (ApiError 0) →
  outbox enqueue → queued success screen. Success auto-returns home in 4s.
- Incident detail: photo, status chip, timeline (trilingual), manager actions seen→in_progress→resolve+note.
- Attendance: SelfieCamera → steps UI (GPS→BLE zone→upload) → punch-in → result screen
  (Verified+/Verified/Flagged + late chip); 409 → toast; offline → outbox. History screen w/ month nav.
- Shift screen (8 days), Alerts (optimistic read, deep-link to incident), Profile (lang switcher w/
  PATCH /employees/me, logout confirm).
- EAS: eas.json (development/preview/production), app.json → name "Hogo Plus", ids com.hogoplus.fs,
  Android perms CAMERA/LOCATION/BLUETOOTH_SCAN/CONNECT, iOS infoPlist descriptions, expo-camera/
  expo-location/ble-plx plugins. BLE isolated behind BleScanner (noop on Expo Go/web — never crashes).

### Testing (iteration_2)
- Testing agent: all UI flows pass in all 3 languages, zero i18n key leaks, registration walked to selfie.
- Camera-gated flows validated via exact-payload API sequence (incident create w/ upload → manager
  triage → notifications; punch-in verified inside geofence → punch-out → duplicate 409).
- Known device-only validations: real camera capture + view-shot watermark + BLE verified_plus require
  Expo Go / dev build (documented for user).

### Phase 2 Part 2 backlog
- Forms engine renderer (schema_json), manager approval screens (registrations/forms/swaps),
  shift swap flow, Time Office flagged-attendance approval, dept attendance dashboard.

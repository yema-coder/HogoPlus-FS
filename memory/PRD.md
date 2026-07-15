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

## Phase 4 — AI Services + Production Storage + Integrations (June 2026) — COMPLETE

### Part A — Production storage (Cloudflare R2)
- FILE_STORAGE_MODE=s3 live. S3Storage: sigv4, region auto, NO ACLs (R2), presigned GET 24h with
  ResponseContentType override (browsers need image/jpeg, R2 stores octet-stream otherwise).
- Migration: scripts/migrate_uploads_to_r2.py — 8 files migrated, keys preserved.
- Backups: nightly 02:30 IST (21:00 UTC beat) pg_dump→gzip→R2 backups/YYYY-MM-DD.sql.gz, keep 14.
  Manual: POST /api/admin/backup-now (CGM/MD). Proof: backups/2026-07-14.sql.gz.
- Secrets in backend/.env (NEVER print): S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY,
  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION=ap-south-1, EMERGENT_LLM_KEY.
  NOTE: must be re-added in Deployment→Secrets at deploy time.

### Part B — Face verification (Rekognition: CompareFaces/DetectFaces/DetectText ONLY)
- employees.reference_selfie_key/set_at; attendance.face_match_score/face_verified.
- Bootstrap: registration approval sets reference from selfie; else FIRST punch selfie (audit event).
- Celery task app.tasks.verify_face (async, never blocks punch): ≥90 verified=true; <80 false +
  flagged/face_mismatch + notify TIME_OFFICE manager; 80-89 borderline (null, level kept);
  Rekognition infra error → null + rekognition:failures counter (NEVER flag); InvalidParameter
  (no face) → score 0 (real mismatch).
- POST /api/admin/employees/{id}/reset-reference-selfie (TO mgr/CGM/MD).
- DetectFaces gate on registration selfie (0 faces → 400 trilingual, fail-open on infra errors, skipped in TESTING).
- Flagged queue returns selfie_url + reference_selfie_url (presigned) + score; mobile shows side-by-side.

### Part C — AI services (Universal Key, gemini-2.5-flash, temp 0, all return value+confidence+model)
- POST /api/ai/anpr {photo_key} → vision → normalize+regex ^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$ →
  fallback Rekognition DetectText. Smoke: MH12AB1234 @ 1.0.
- POST /api/ai/gauge-read {photo_key,expected_min/max} → value+in_range. Smoke: 72.5 Brix.
- POST /api/ai/voice-fill {audio_key,form_definition_id} → Whisper (Devanagari-bias prompt) → LLM maps
  to schema (only text/number/select/toggle; select must match option verbatim; omit uncertain).
- POST /api/ai/chat → embed query (LOCAL fastembed sentence-transformers/paraphrase-multilingual-
  MiniLM-L12-v2, 384-dim, cache /app/backend/.fastembed_cache) → pgvector cosine top-6 (gate 0.78) →
  grounded answer in user language + citations; trilingual honest fallback; history last 6 turns
  (chat_messages table).
- SOP RAG admin: POST/GET/DELETE /api/admin/sop-docs (PDF→R2→celery sop_ingest: pypdf per-page,
  ~800-token chunks w/ overlap, embed → sop_chunks pgvector). No OCR (text-layer only).
- Incident severity: celery classify_incident_severity after create → severity+severity_reason(EN)+
  timeline ai_severity; critical → notify dept mgr + CGM/MD. Smoke: fire+trapped → critical.
- Nightly report: 06:00 IST (00:30 UTC) → per-dept attendance/submissions/incidents/approvals-aging →
  fpdf2 + Noto Sans Devanagari (bundled assets/fonts) + set_text_shaping(True) + set_fallback_fonts
  (Deva font lacks Latin letters!) → R2 reports/YYYY-MM-DD/factory-report-{mr,en}.pdf → notify CGM/MD
  presigned link. Manual POST /api/admin/generate-report {date}. Devanagari visually verified.
- Cost: redis cache 24h by (endpoint,photo_key); GET /api/admin/ai-usage counters (CGM/MD).
- SMS stubs: OTP_MODE=demo; MSG91Sender + SMSGatewayHubSender raise NotConfigured until keys arrive.

### Part D — Mobile wiring
- AnprTextInput (text field ai_hook=anpr): camera scan btn → upload → /ai/anpr → autofill + AI chip
  (confidence %). Silent fallback on failure. Manual edit clears chip (never locks).
- gauge_read photo → auto-fill first number field via /ai/gauge-read + out-of-range toast.
- VoiceFillButton FAB (forms with 2+ fillable fields): ≤60s expo-audio rec → /ai/voice-fill →
  prefill + AI chips + toast.
- Sahayak chat: app/sahayak.tsx (entry: profile testID sahayak-entry). Bubbles + citation chips +
  trilingual empty state.
- Incident detail: SeverityChip (muted/amber/red) + AI reason card + one 8s re-poll; approvals
  incidents sort critical-first + severity chip.
- Time Office queue: side-by-side reference/punch selfies + Face match % for face_mismatch rows.
- i18n: 272 keys ×3 (was 247, +25), parity script green.

### Phase 4 infra notes
- Pod recycle wiped PG16+redis: reinstalled via PGDG apt (postgresql-16, postgresql-16-pgvector,
  redis-server), recreated hogo role + hogoplus/hogoplus_test DBs + vector extension, alembic 0001-0003,
  seed.py (401 employees). If it recycles again, repeat those steps.
- Migration 0003: face cols, severity_reason, sop_docs, sop_chunks(vector 384), chat_messages.
- Tests: 99 passed (was 78; +21: test_face_verification.py matrix, test_ai_endpoints.py mocked).
- Demo seeded: face_mismatch row for emp 0056 (ENG worker +917775915271) w/ synthetic selfies.

### Phase 5 backlog (NOT started)
- MD Web Dashboard (web app for MD role) — user will request explicitly.

## Phase 5 — MD Command Center + Backup Hardening (COMPLETE)

### Fix Pack 3 (backup hardening) — done in previous session, verified here
- Celery beat pg_dump → R2 `backups/YYYY-MM-DD/HHMM.sql.gz` every 4 hours, 30-day retention.
- Startup DB integrity check: empty employees table → CRITICAL log, /api/health db_seeded=false,
  CGM notification. NEVER auto-restores.
- `scripts/restore_latest.py` (--latest/--key/--target drill). REAL DR executed this session:
  fork pod wiped PG entirely → reinstalled PG16+pgvector+redis via PGDG apt, recreated hogo role +
  DBs, restored latest R2 backup → 401 employees verified.
- reference_bootstrap flow (flag + reject-clears-reference) covered by
  tests/test_face_verification.py::test_bootstrap_{approve_keeps,reject_clears}_reference.

### MD Command Center web (/app/webdash → React 18 + Vite + TS + Recharts)
- Served by FastAPI at **/api/dash/** (ingress only forwards /api/* to backend; /dashboard on the
  backend 307-redirects there). vite base=/api/dash/, build outDir=/app/backend/webdash_dist,
  mounted in main.py (StaticFiles for assets + index.html fallback route /api/dash{path}).
- Rebuild: `cd /app/webdash && /usr/bin/yarn build` (plain yarn is shim-guarded; use /usr/bin/yarn).
- Auth: same OTP endpoints, JWT in localStorage (hogo_access/hogo_refresh) w/ auto-refresh-once.
  rank>3 → access denied screen. Manager scope enforced server-side (dashboard.py _scope).
- Screens: Overview (KPIs, 13 dept tiles, attendance bar chart, live incident feed, 60s poll),
  /dept/:code drill-down (14-day trends line chart, attendance/submissions/incidents), Approvals
  aging (by-manager tiles + items table, age chips 8h/24h), Attendance register (dept+date select,
  approve/reject flagged for TIME_OFFICE mgr + CGM/MD), Reports & AI (PDF list from R2, generate,
  ai-usage chart — CGM/MD only; Sahayak chat for all), Admin (geofence form, assign manager,
  missing phones, change role incl. MD creation, SOP upload, backup-now) — CGM/MD only.
- i18n: compact web dict in src/i18n.tsx (~110 keys ×3 en/hi/mr), Baloo 2 + Noto Sans Devanagari
  via @fontsource. Lang persisted in localStorage hogo_lang.
- NEW backend endpoint: GET /api/admin/employees?search=&missing_phone= (rank≤2) for admin screen.
- Tests: **111 passed** (109 + 2 new admin employee search tests).
- README rewritten: DR steps + LAUNCH DAY RUNBOOK (deploy→secrets→health→geofence→managers→
  phones→MD→SOPs).


### SMS integration — SMSGatewayHub (post-Phase-5 add-on)
- Keys in backend/.env: SMSGATEWAYHUB_API_KEY / SENDER_ID / DLT_TEMPLATE_ID + OTP_TEMPLATE_TEXT
  (exact DLT template, {#var#} x2). NEVER log/echo values.
- app/otp.py SMSGatewayHubSender fully wired: GET https://www.smsgatewayhub.com/api/mt/SendSMS,
  params APIKey/senderid/channel=2/DCS=0/flashsms=0/number(no +)/text/route=1/dlttemplateid
  (+EntityId only if configured). build_message(): 1st {#var#}=OTP, 2nd {#var#}="5" (TTL min),
  no other text altered (DLT scrubbing). Success = ErrorCode "000"/"0".
- send() fallback: on any provider error → logger.error; if DEMO_OTP_ENABLED (non-prod) log
  fallback demo OTP and DON'T raise; in prod raise SMSDeliveryError → auth send-otp returns 502.
- OTP_MODE still "demo". POST /api/admin/test-sms {phone} (rank≤2) sends a REAL OTP via the
  provider (stores hash in redis so it's usable) and returns raw provider JSON; 502 on error.
- Tests: tests/test_sms_sender.py (7 mocked: template substitution, payload shape, error code,
  demo fallback, prod raise, mode selection, endpoint auth). TOTAL NOW **118 passed**.
- README runbook secrets corrected: OTP_MODE=smsgatewayhub (+ SMSGATEWAYHUB_* / OTP_TEMPLATE_TEXT),
  with test-sms verification step before flipping mode.


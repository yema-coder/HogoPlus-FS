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


### Mobile Fix Pack (real-device feedback) — 4 items (COMPLETE)
1. BRANDING: user's eye logo processed (transparent outside, inner negative space filled WHITE per
   user correction; blue artwork untouched) → assets/images/logo.png (+ icon/adaptive/splash/favicon
   all on WHITE square bg per user; app.json name "HogoPlus-FS", splash+adaptive bg #FFFFFF).
   Logo shown on: language + phone screens (Image, testIDs language-logo/login-logo), NEW teal Home
   brand header (centered 36px logo + "HogoPlus-FS", avatar initials right → profile, greeting/dept
   second row), webdash sidebar + login (src/logo.png, vite-env.d.ts added for png imports).
2. CAMERA CLOSE: 56px ✕ top-left w/ t("common.close") a11y label on: incident capture camera,
   SelfieCamera (new onClose prop; punch + register-selfie pass router.back), PhotoCaptureModal
   (moved close to top-left, 56px). Hardware back = default stack pop / Modal onRequestClose.
3. PHOTO SUBMIT BUG ROOT CAUSE: RN FormData on Android (Expo Go) posted an EMPTY file part →
   backend 400 "Empty file" (seen in logs) → client collapsed non-0 status into errors.server.
   FIX: uploadFile native path now uses expo-file-system/legacy uploadAsync MULTIPART (streams real
   bytes) w/ 401-refresh-retry; web path unchanged (blob). burnInSafe() wrapper never throws (falls
   back to raw photo — watermark burn-in via view-shot may fail in Expo Go/Fabric, MUST re-test
   watermark on EAS build). 400/413 now show errors.uploadRejected(+detail); status 0 still → outbox.
   E2E evidence: empty part→400 repro, real jpg→200→incident created "submitted".
4. PERMISSION PRIMER: app/permissions.tsx (one-time post-login, native only — Platform gate in
   index.tsx), 3 cards Camera/Location/Notifications + one Allow → sequential system dialogs;
   authStore.permsPrimed (storage hogo.permsPrimed). BLE Android12+ asked LAZILY on first real scan
   (ensureBlePermissions in BleScanner.ts + one-time toast perm.bleExplain, storage hogo.bleAsked);
   gps skip note perm.gpsOffNote on punch steps.
- i18n: 284 keys ×3 (was 272; +12: common.close, errors.uploadRejected, perm.*). Parity GREEN.
- Tests: backend 118/118 (unchanged); testing_agent iteration_6 all green (web flows + regression).
- NOTE: pod was RESET mid-session again (PG/redis wiped) → re-ran full DR (PGDG apt install,
  role/DB create, restore_latest.py from R2, 401 employees). This is the 2nd reset; DR is routine.


### Deployment failure analysis (mongo_cluster_setup) — RESOLVED in sandbox
- Deploy failed at v3.InitialDeploy.MongoClusterSetup "list source databases" exit 1: the deployer
  snapshots the SANDBOX's local MongoDB, but the pod had been reset (3rd time) — supervisord +
  mongod + postgres/redis packages wiped → local mongo unreachable → step failed.
- Fixed: created idempotent /app/scripts/sandbox_recover.sh (PGDG install, role/DB create, R2
  restore via restore_latest.py, supervisord + all services). Run with `sudo bash` after any reset.
- Code fix: restore_latest.py now uses sys.executable for the alembic subprocess (was bare
  "python" which lacks alembic under sudo/root PATH).
- Gotcha learned: NEVER SIGTERM/pkill postgres while supervisord manages it — smart shutdown hangs
  in "database system is shutting down"; recover with supervisorctl stop postgresql + pkill -9 +
  rm postmaster.pid + start.
- PRODUCTION REQUIREMENTS (unchanged, per runbook): Emergent deploy only provisions managed Mongo
  (unused by this app). App needs Deployment→Secrets: DATABASE_URL (external managed Postgres
  WITH pgvector, e.g. Neon/Supabase), REDIS_URL/CELERY_BROKER_URL/CELERY_RESULT_BACKEND (e.g.
  Upstash), + R2/AWS/LLM/SMS keys. Startup is non-fatal if DB unreachable (health db_seeded:false).
- deployment_agent flags Postgres/Redis as platform "blockers" — expected; resolved via external
  managed services through secrets, NOT by migrating to Mongo (architecture decision across 5 phases).


## Prompt 6 Part 2/3 — UX Pack Mobile UI + Opportunistic ANPR (2026-07 fork) — DONE
- 2.1 Photo-first complaint flow: home/pending tile → /incident/capture opens CAMERA immediately
  (safe-area ✕ close, GPS chip in parallel); detail screen = watermarked photo + dept selector +
  description + 60s expo-audio voice note (reused VoiceFieldInput) → submit as category='other'.
  incident/category.tsx DELETED (no category pre-pick).
- 2.2 AI confirmation card: success.tsx polls incident detail (3s × 12) for ai_suggested_*;
  card shows category+dept+confidence with Accept (confirm-routing {}) / Change (scrollable modal:
  category chips + dept list → confirm-routing {category, department_code}). ai_timeout path
  (10-min auto-apply) demonstrated live on Neon: sweep set ai_confirmed_by='ai_timeout'.
- 2.3 Grievance→Complaint rename trilingual (mobile locales + webdash i18n). 2.4 SelfieCamera ✕
  now uses useSafeAreaInsets. 2.5 swap/new.tsx searchable colleague picker (name/emp_id filter).
- 2.6 Onboarding: register-name → register-selfie (register-department.tsx DELETED; register body
  has no department_code). Approvals>Registrations Approve opens assignment modal (dept list +
  role chips Worker/Staff/Clerk/Manager + emp_id input) → POST /admin/employees/{id}/approve body.
- 2.7 Resolve flow requires resolution photo (PhotoCaptureModal; confirm disabled w/o photo);
  incident detail shows resolution photo + detected_plate chip (ANPR). Webdash Overview/Department
  feeds show 🚗 plate; dashboard.py serializes detected_plate.
- 2.8 punch-out reminder already existed (celery beat 15-min, redis once-per-day guard, mocked
  clock test) — verified registered after celery restart.
- BUGFIX: aws.py had DUPLICATE detect_text defs (2nd list[dict] shadowed 1st list[str]) →
  removed str version; tasks.extract_plate now handles dict/str lines. Celery worker restarted
  (was running stale code without detect_plate/punchout/ai_timeout tasks — remember to restart
  celery after tasks.py changes!).
- i18n: +9 new keys ×3 (incident.captureHint/voiceNote/aiCardTitle/aiWaiting/aiAccept/aiChange/
  aiRouted/aiLater/detectedPlate, reports.resolutionPhoto*, approvals.assign*/empId/approveTitle/
  newJoinee, swap.search). Parity GREEN en/hi/mr.
- Tests: backend 126/126 green; testing_agent iteration_7 ALL GREEN (1 LOW modal-overflow issue →
  fixed: edit modal content in ScrollView, maxHeight 75%, actions pinned). Reusable live suite:
  /app/backend/tests/live_ux_pack_spotcheck.py.

## Prompt 7 — VIDEO + PASSWORD LOGIN + POLISH PACK (2026-07 fork) — DONE (deployment NOT triggered; owner publishes)
- Part A Video: capture.tsx photo/video toggle (30s auto-stop countdown, 720p, mode="video" CameraView),
  offline disables video toggle (NetInfo) w/ trilingual note; upload mp4/mov (ftyp magic, 40MB cap →
  trilingual 413 video_too_large); playback expo-video (mobile detail) + HTML5 <video> (dash feed);
  incidents.video_key nullable + photo_key made nullable (validator: one media required); classifier
  text+audio only for video (no image); ANPR skipped for video incidents.
  NATIVE MODULES/PERMISSIONS ADDED: expo-video ~3.0.16 (+plugin), android RECORD_AUDIO,
  iOS NSMicrophoneUsageDescription, expo-camera plugin microphonePermission string (was False!).
- Part B Password login (webdash MD/CGM only): employees.password_hash+must_change_password
  (alembic 0005); passlib bcrypt helpers in security.py; POST /auth/password-login (redis lockout
  5/15min pwlogin:fail:{emp_id}, trilingual 429; rank>2 → 403), /auth/change-password,
  /admin/employees/{id}/set-password (rank<=2). Webdash Login has OTP/Password tabs + forced-change
  screen; sidebar Change-password modal (top mgmt). CGM creds: 0001/Hogo@2026Cgm (test_credentials.md).
- Part C Plate search: GET /api/dashboard/plates/search?q= (ilike on incidents.detected_plate +
  jsonb_array_elements_text on form_submissions.detected_plates; manager scoped to own dept);
  webdash Vehicles screen + Overview feed filter box.
- Part D Address polish: address_text on incidents+form_submissions; src/utils/geocode.ts
  (Location.reverseGeocodeAsync, never throws); geocoded at capture in capture.tsx / FormRenderer
  (incl. offline enqueue) / punch.tsx (passed to result screen); location blocks: incident detail
  (mobile), attendance result (zone > address > coords), dashboard feed 📍 line.
- Part E Permission primer ROOT CAUSES FIXED: (1) otp.tsx/pending.tsx bypassed index gate with
  router.replace("/(tabs)/home") → primer never ran on first login — now replace("/"); (2)
  authStore.hydrate never restored hogo.permsPrimed — now restored; (3) one-time re-prime if
  camera/location still undetermined (hogo.permsReprimed flag). acquireGps already does inline
  request (defense-in-depth). ON-DEVICE VERIFY needed: primer runs after first login on real device.
- Tests: 136/136 pytest (test_prompt7.py: cap/magic/presign/role gates/lockout/forced-change/
  worker-403/plate-scope/address). testing_agent iteration_8 ALL GREEN. Live evidence: ANPR
  MH14GH7777 via real Rekognition on photo-first photo; mp4 presign content-type video/mp4;
  password E2E in browser. i18n parity 309 keys ×3.
- LESSON: search_replace occasionally silently mis-applied during heavy parallel batches this
  session (models.py tail garbage, files.py cap block, App.tsx import) — ALWAYS re-verify with
  grep + compile after batched edits.

## Pre-republish fixes (launch-critical, 2026-07-15 evening)
1. SECRETS: Deployment Panel "Secrets" tab IS the runtime source of truth (confirmed via support);
   .env / .env.* / *.env RESTORED to .gitignore (Save to GitHub respects .gitignore — secrets never
   reach the repo). Deploy does NOT need .env shipped.
2. OOM ROOT CAUSE of production 520 + restart loop: main.py startup eagerly warmed the fastembed
   ONNX model → API worker RSS 707MB at boot; on the 1Gi prod container (plus celery worker+beat)
   → OOMKilled crash loop. FIX: warm-up removed; get_model() stays lazy singleton. Startup RSS now
   102MB. First AI chat call loads model on demand → ~846MB in that process (verified working).
   RECOMMENDATION for owner: pick ≥2GiB deploy tier if AI chat/RAG will be used heavily.
   Sandbox restarts were NOT crashes: uvicorn --reload (dev) + controlled supervisorctl restarts;
   cgroup oom_kill=0 here.
3. Celery worker+beat: independent supervisor programs — survived 6+ backend restarts (uptime 1h30m).
   Lost in-flight celery tasks are self-healing: classify → ai_timeout sweep (10 min), reminders/
   escalations → recurring beat sweeps; punch/incident submits retry via mobile outbox on status 0.
4. Expo tunnel enabled in supervisor (--tunnel + @expo/ngrok) per deployment health check.
   Tests still 136/136 after all changes.

## UI polish pack before APK (2026-07-16) — DONE
- Fix 1: capture detail screen compact — media card 24% of viewport (tap → full-screen viewer modal
  with ✕), one-line location, dept row 48px, 2-3 line description, voice button, Submit visible with
  ZERO scroll at 390x640 (measured: submit bottom 573px). Watermark burn-in moved to an off-screen
  full-aspect view (quality unchanged, cover-crop avoided).
- Fix 2: Home header teal → WHITE band: #FFFFFF bg, 1px bottom border #D4D1CA + soft elevation,
  title in PRIMARY TEAL #0B4F6C (pairs with logo), avatar chip brandTertiary/teal, StatusBar dark.
  ScreenHeader (other screens) was already neutral — untouched. Tab bar untouched.
- ENV NOTE: container got recycled mid-session; new image has NO postgres user → old
  supervisord_hogo.conf [program:postgresql]/[redis] sections blocked supervisord startup.
  Cleaned conf (celery worker+beat only now). @expo/ngrok had to be reinstalled globally after
  recycle (needed for --tunnel). If services are ALL down after a recycle: start supervisord
  manually and check /etc/supervisor/conf.d/supervisord_hogo.conf validity.
- APK build: NO EAS CLI — Emergent Publish panel generates .apk/.aab (inputs: app name + icon).
  Backend URL comes from Deployment Secrets (EXPO_PUBLIC_BACKEND_URL → https://hogo-backend-phase1.emergent.host).
  OTA/EAS Update NOT documented on platform — update path is rebuild + redistribute.

## Prompt 8 — Build fix + OTP whitelist + BLE-MAC beacons (2026-06 fork) — DONE
- A) ANDROID BUILD FIX (duplicate <uses-permission>): app.json android.permissions reduced to
  ["POST_NOTIFICATIONS"] only. CAMERA/RECORD_AUDIO injected by expo-camera+expo-audio plugins,
  ACCESS_FINE/COARSE_LOCATION by expo-location plugin, BLUETOOTH_SCAN(neverForLocation)/CONNECT/
  BLUETOOTH/BLUETOOTH_ADMIN by react-native-ble-plx plugin. Verified via real `expo prebuild` in
  /tmp sandbox copy (NEVER prebuild inside /app/frontend — leaves android/ dir + edits package.json):
  every permission exactly once in AndroidManifest.xml. The 2 `uses-permission-sdk-23` location
  entries (maxSdkVersion=30, from ble-plx) are a DIFFERENT element type — legal, not duplicates.
- B) DEMO OTP WHITELIST: settings.demo_otp_whitelist (env DEMO_OTP_WHITELIST, comma-separated) +
  demo_otp_whitelist_set property. verify-otp demo shortcut now requires enabled AND whitelisted
  AND employee exists (replaces all-seeded-numbers behavior). Real OTP flow/rate-limits/lockout
  unchanged. Prod .env whitelist: +918483029039 (CGM), +917972540971 (worker — Play-reviewer acct).
  conftest whitelists all test PHONES + +919777777701 + +919888888801 (registered during tests);
  NON_WHITELISTED_PHONE +919000000031 (emp 0031) seeded to prove rejection.
- C) BLE-MAC BEACON MATCHING (vendor ships MAC-based, non-configurable beacons):
  * ble_beacons.mac_address String(17) nullable UNIQUE (alembic 0006, applied to Neon).
  * BeaconIn/PatchIn: mac_address validated ^[0-9A-F]{2}(:..){5}$, normalized uppercase
    (schemas.normalize_mac); beacon_uuid now optional (default ""); duplicate MAC → 409.
  * punch-in: backend matches sent MAC against active registered beacons (uppercase equality),
    resolves ble_zone=zone_label_en; registered→verified_plus, unregistered→ignored (verified),
    no BLE→verified. PunchInIn.ble_zone REMOVED (backend resolves zone).
  * NEW GET /api/attendance/beacon-macs (any approved employee) → {"macs":[active registered MACs]}.
  * Mobile BleScanner.scan(timeoutMs, registeredMacs): matches device.id (Android=MAC,
    case-insensitive) against the set, strongest-RSSI wins, iBeacon/name filtering removed;
    empty list → instant null; noop fallback + 3s scan window unchanged. punch.tsx fetches
    beacon-macs (offline-safe catch→[]) and sends ble_beacon_id=matched MAC only.
  * Webdash Admin: new "📡 BLE beacons" card (list/add/toggle-active/delete, client-side MAC
    format validation, trilingual i18n keys beacons/macAddress/zoneEn|Hi|Mr/addBeacon/invalidMac).
- Tests: 140/140 pytest (was 136; +2 whitelist auth, +2 MAC attendance incl. beacon-macs;
  beacon CRUD test now covers mac normalize/422/409). Prod verified: CGM demo login 200,
  non-whitelisted seeded 401, beacon-macs 401/200, beacon create normalized + deleted.
- ENV NOTE: this fork's container has NO local postgres/redis (managed Neon/Upstash cutover).
  For pytest: apt install postgresql postgresql-server-dev-15 redis-server, build pgvector v0.8.0
  from source (make && make install), create role hogo/hogo_secret SUPERUSER + db hogoplus_test,
  service postgresql start && service redis-server start.

## Prompt 9 — ANPR PRODUCTION FIX + DETECTION UPGRADE + RESULT-CARD UI (2026-06 fork) — DONE
- ROOT CAUSE (proven with evidence): production deployment runs ONLY the FastAPI process (no
  Celery worker), and its .delay() enqueues to Upstash silently FAILED (swallowed by
  `except Exception: pass`) — repro: incident created on prod backend → 95s later queue len 0,
  zero tasks received by a live worker on the same broker. Secondary defect: strict plate regex
  missed OCR confusables (Rekognition read MH02FX2660 as "MHO2FX2660" — O/0 confusion).
- FIX: incident AI (ANPR + classification) now runs IN-PROCESS via FastAPI BackgroundTasks
  (tasks.run_incident_ai_background — ANPR first, LLM classify second; forms/resolution use
  run_plate_detection_background). Celery task detect_plate kept for manual backfills; beat
  sweeps unchanged. Enqueue guarded by TESTING env in routes.
- DETECTION UPGRADE (app/anpr.py): DetectText → extract_plate_from_lines (exact regex + Indian
  state-code check, then POSITIONAL confusable coercion O→0,I→1,Z→2,S→5,B→8,G→6 etc.);
  if no valid plate → llm_plate_fallback (ai_core.vision_json, Universal Key) — incidents only.
  Outcome ALWAYS stored: incidents.plate_status(pending/detected/not_detected), plate_confidence,
  plate_source(rekognition/llm_vision), plate_reason(no_text_found/no_valid_plate/detection_failed)
  — migration 0008... (0007_anpr_pipeline, applied to Neon, legacy detected rows backfilled).
  Every outcome logged INFO "ANPR incident/<id> → status=... plate=...".
- RESULT-CARD UI: mobile incident/[id].tsx — media card w/ status badge, Detected Number Plate
  card (big mono plate + confidence % + expo-clipboard copy) OR "Number Plate Not Detected"
  banner + translated reason OR pending spinner (re-polls ≤5×8s); Object Location + Device
  Location blocks (same data, labeled separately); captured-at row. Webdash Department.tsx —
  incidents clickable → IncidentModal (same layout, navigator.clipboard copy); dashboard dept
  endpoint now returns photo_url/video_url/plate_*/address_text/gps/description for incidents.
  i18n: 12 new keys ×3 langs (mobile locales + webdash i18n.tsx).
- ACCEPTANCE DEMONSTRATED: user's original prod incident 668d75cc (16/07 21:01 IST) reprocessed
  via celery → plate MH02FX2660 conf 64.2 rekognition stored in prod Neon; NEW incident d37baac1
  created via API → in-process background task detected MH02FX2660 with NO celery; screenshots
  of mobile + webdash result cards taken.
- TESTS: 147/147 (was 140; +7: test_prompt9_anpr.py normalization/fallback/persistence + ux_pack updated).
- ⚠️ DEPLOYMENT PREREQS (user must verify in Deployment Panel Secrets before Publish): AWS_ACCESS_KEY_ID,
  AWS_SECRET_ACCESS_KEY, AWS_REGION, EMERGENT_LLM_KEY must exist (ANPR now runs in the API container).
  CELERY_* secrets likely missing/wrong there (the original root cause) — needed only for sweeps.
- NOTE: attendance face-verification + beat sweeps still depend on the sandbox Celery worker —
  same architectural gap, NOT fixed (out of scope, flag for future prompt).

## Prompt 10 (Part D) — ALL Celery work now in-process for production (2026-06 fork) — DONE
- ARCHITECTURE: production containers run ONLY the FastAPI process. All async/scheduled work
  now executes there:
  * Per-request → FastAPI BackgroundTasks: face verification (attendance punch-in →
    tasks.run_face_verification_background), SOP embedding (admin sop upload →
    run_sop_ingest_background, releases ONNX model after — embeddings.release_model() with
    gc+malloc_trim: 663MB spike → 100MB after release), incident AI (Prompt 9). All wrapped
    with INFO outcome logs; every silent `except: pass` in task paths removed/logged.
  * Scheduled → app/scheduler.py APScheduler AsyncIOScheduler started in main.py startup
    (guarded: once per process, skipped when TESTING/DISABLE_SCHEDULER=true). JOBS mirror old
    beat: escalation */30, ai timeout */5, punchout reminder */15, backup 4h (3,7,11,15,19,23 UTC),
    nightly report 00:30 UTC.
  * CROSS-CONTAINER DEDUPE: sandbox + prod share Neon/Upstash → every run takes Redis NX lock
    `jobs:lock:<name>` (async in scheduler, _job_lock_sync in the celery task bodies). PROVEN
    live: 20:35 UTC APScheduler ran sweep, celery beat task returned {'skipped':'lock'}.
    Celery worker+beat still run in sandbox (redundancy) — locks make double-run impossible.
- BACKUP FIX (bonus root cause): pg_dump was SILENTLY FAILING against Neon even in sandbox
  ("server version mismatch" — Neon PG17 vs client 15) → 4-hourly "backups" were broken.
  run_backup_sync now falls back to a pure-Python data-only SQL dump via asyncpg
  (_python_sql_dump_async: INSERTs + session_replication_role=replica; restore = alembic
  upgrade head + run file). Verified: backups/2026-07-17/0157.sql.gz uploaded to R2, 523KB
  uncompressed, 402 employees/402 shift_assignments rows. Result includes "method" field.
- PROOFS (preview backend = code that will deploy): backup-now → backups/2026-07-17/0157.sql.gz
  (method=python); punch-in → in-process face verification score 100.0 (log:
  "Face verification attendance/e2974799… → {'score': 100.0, 'face_verified': True}"; proof
  attendance row deleted after); scheduler startup logs list all 5 jobs registered.
- MEMORY: API worker steady-state RSS ~135MB with scheduler running; SOP-embed spike ~660MB
  then back to ~100-135MB after release_model() (malloc_trim). Safe on 1Gi.
- Tests: 152/152 (+5: scheduler registry, TESTING guard, lock single-execution across
  sync+async paths, _sql_literal, python dump fallback). requirements.txt += APScheduler 3.11.3.
- ⚠️ PRODUCTION ACTIVATION: user must Publish (redeploy). After redeploy, prod logs will show
  "scheduler: N jobs registered IN-PROCESS". Deployment Secrets must include AWS_*,
  EMERGENT_LLM_KEY (already required by Prompt 9) — CELERY_* no longer needed in prod.

## Prompt 11 — Submit speed + EyeLoader + logo assets (2026-06, FINAL PRE-BUILD) ✅ DONE
- OPTIMISTIC SUBMIT (photo path): capture.tsx submit() now ALWAYS enqueues to the outbox
  (photo + optional voice note as files[{field:"voice_note_key"}]) and navigates instantly to
  /incident/success?oid=<outboxId> (measured 117ms; burn-in+compress ~1-2s before that).
  Compression unchanged (burnIn.ts: quality 0.7, max 1600px — already met acceptance).
  Video path unchanged (network-required, direct upload, queued=0/rid params still supported).
- outbox.ts: new state uploadingId (chip driver) + results{oid → incident id | null=rejected,
  in-memory only}; enqueue() returns id; incident branch uploads aux files (voice note;
  non-network aux failure won't block the report).
- success.tsx: oid mode watches the outbox live — Saved!/EyeLoader (uploading) → willRetryBody
  (retries>0) → Complaint sent! + id + existing AI card polling (effectiveRid = rid ?? results[oid]).
  Permanent rejection → uploadFailed copy. testIDs: incident-uploading-icon/queued/sent.
- reports.tsx outbox rows: chips Uploading… (accent + mini EyeLoader) / Will retry / Waiting to send.
- EyeLoader (/src/components/EyeLoader.tsx): left→hold→right→hold→centre→blink, native driver,
  AppState-paused. Replaced ALL ActivityIndicators (16 files, grep=0 left). BigButton loading
  uses it too. Home header: BlinkingLogo idle blink (testID home-brand-eye). Webdash: CSS
  .eye-loader/.eye-iris keyframes in styles.css + Loading() markup in components.tsx.
- ASSETS: icon.png + splash-image.png regenerated 1:1 from user's hogoplus_logo_white_1024.png;
  adaptive-icon.png = same logo at 66% safe-zone on white 1024; favicon 96px; app.json splash
  bg already #FFFFFF (untouched). Deleted orphans: app-image.png, partial-react-logo.png,
  react-logo*.png. In-app logo.png kept (transparent variant, same artwork — attached
  hogoplus_logo_white.png is white-bg RGB, worse for headers).
- Extra fixes: pointerEvents prop→style (capture viewer), reverseGeocode web guard (Geocoding
  API removed on web SDK49; native unaffected).
- i18n added (en/hi/mr): status.uploading, status.willRetry, incident.uploadingBody/
  willRetryBody/uploadFailed.
- Testing: iteration_12.json — ALL PASS (frontend agent, live prod backend; incident #835FEA22
  created). tsc + eslint clean. Icon/splash verification requires the Android build (v1.0.2).

## Prompt 12 — REAL-logo EyeLoader rebuild + incident audio E2E (2026-06) ✅ DONE
- EYELOADER REBUILT per user rejection: now a two-layer composition of the REAL logo using
  user-supplied assets /app/frontend/assets/images/eye-base.png (502×408, socket filled white)
  + eye-iris.png (202×202). Geometry: iris centre 51.4%W/54.7%H, diameter 40%W, travel ±12%W.
  ~2s loop: left 280ms → hold 250 → right 460 → hold 250 → centre → blink (whole logo scaleY
  0.08, 100+100ms). IMPORTANT WEB LESSON: Animated.Image transform does NOT apply on RN-web —
  iris must be wrapped in Animated.View (fixed; verified translateX -5.9→+5.9→0 + scaleY 0.947
  blink via computed styles). Same 16 call sites (color prop removed — image has brand colours).
  Home idle blink delay 6800ms. Webdash: real-image CSS twin (.eye-base/.eye-iris in styles.css,
  imgs imported in components.tsx Loading()); frames captured showing iris left/mid/right.
- INCIDENT AUDIO E2E (approver playback): backend adds voice_note_url to incidents _out and
  both dashboard payloads (overview feed + department incidents); storage._content_type maps
  .m4a → audio/mp4 (missing from Python mimetypes). Mobile: new
  /app/frontend/src/components/AudioPlayerCard.tsx (expo-audio useAudioPlayer +
  useAudioPlayerStatus; play/pause, progress bar, elapsed/total) rendered in incident/[id].tsx
  (testID incident-voice-player). Webdash IncidentModal: <audio data-testid=modal-voice-audio>
  + i18n voiceNote key. Webdash rebuilt (yarn build → /app/backend/webdash_dist).
- LIVE E2E PROOF (prod Neon/R2): real Marathi gTTS voice note (10.2s mp3) uploaded by worker
  +917972540971 → incident 5b3ccaa2-1bb6-40aa-8a5a-206432a71124 (PRODUCTION,
  machine_breakdown, voice key 2c92689108ce4f52bd785b7c5c9f703d.mp3) → CGM mobile playback
  verified (0:03/0:10 progress) → presigned GET 200 audio/mpeg 81408 bytes → webdash modal
  audio duration 10.176s + play() advanced. AI even transcribed the Marathi voice note into the
  severity assessment. KEEP this incident (referenced by tests).
- Outbox optimistic path carries voice notes as files[{field:"voice_note_key"}] (prompt 11).
- NOTE: OTP send has 10-min rate limit (otp:send:<phone> redis key) — clear via redis_client
  when repeated logins throttle testing. gtts pinned click conflict: click restored to >=8.4.2.
- Testing: iteration_13.json PASS (one web-only iris finding — FIXED after, re-verified
  numerically). User will now trigger the v1.0.2 build.

## Prompt 13 — CGM/MD dept switcher + prod employee Yema G (2026-06) ✅ DONE
- DEPT SWITCHER (mobile "My Department" tab): rank<=2 (CGM/MD) get a horizontal chip row
  (testID dept-selector, chips dept-chip-<CODE>) of all 13 departments (trilingual from
  /api/departments, own dept first + default). Selecting loads that dept's forms
  (listForms(dept)) + dept-wide submissions (listSubmissions({department_code})); header title
  = selected dept name; form tiles push /form/[id]?dept=<code> (form/[id].tsx accepts dept
  param for the definitions fetch). Rank>=3 unchanged (no chips, locked to own dept).
- BACKEND SCOPING TIGHTENED (forms.py): list_forms → 403 if department_code != own && rank>2
  (previously managers could silently browse any dept); submit_form → 403 threshold rank>2
  (was >3 — managers could cross-submit before!). Submission stays stamped with
  definition.department_code (CGM cross-submits carry the selected dept).
- TESTS: 158/158 passing (was 152; +6 in tests/test_dept_switcher.py; 2 tests in
  test_forms.py REWRITTEN to expect 403: test_worker_other_dept_forms_forbidden,
  test_manager_other_dept_forms_forbidden). Local test infra reinstalled this fork:
  apt postgresql+redis-server, role hogo/hogo_secret, db hogoplus_test, pgvector v0.8.0
  BUILT FROM SOURCE (apt has no postgresql-15-pgvector; needed postgresql-server-dev-15 +
  make install from github pgvector tag v0.8.0, then CREATE EXTENSION vector).
- i18n added: forms.viewDept (en "View department" / hi "विभाग देखें" / mr "विभाग पहा").
- PROD EMPLOYEE (REAL, live immediately): Yema G, emp_id 1212 (next free numeric), phone
  +919309491145, TIME_OFFICE / Manager, onboarding approved, ShiftAssignment GEN baseline
  eff 2026-07-17. Employee count 402 → 403. NOT whitelisted (real SMS OTP once owner flips
  OTP_MODE). TIME_OFFICE.manager_employee_id already set to another employee (untouched) —
  Yema qualifies via is_dept_manager role+dept rule. Verified live with a minted JWT:
  GET /api/attendance/flagged 200 (3 items), GET /api/admin/employees/pending 200; worker 403.
- E2 frontend pass iteration_14.json: ALL PASS (13 chips, ADMIN first/default for CGM,
  cross-dept form renders, worker sees no chips, Marathi labels OK).
- Ships in v1.0.3 consolidated build (mobile side); Yema's record already live.

## Prompt 13 (user numbering) — Speed Pass #2 + Media Viewer + Brand Polish (2026-06) ✅ DONE
- A SPEED: authStore.hydrate is now CACHE-FIRST (paint Home from stored hogo.profile, getMe
  revalidates in background → 0 blocking startup API calls); Approvals lists SWR-cached
  (AsyncStorage hogo.cache.approvals, hydrate on mount + persist after loadAll); SkeletonRows
  component (/src/components/Skeleton.tsx) on Approvals + My Reports first load; reports
  refresh strip (EyeLoader, testID reports-refresh-strip); OTP delay hint (testID
  otp-delay-hint, i18n auth.otpDelay); success AI polling 2s×10 then 5s (MAX_POLLS 14).
  Measured (Expo web): cold→interactive 691ms, login→home 3309ms, home→reports 101ms,
  approvals skeleton 200ms/ready 785ms.
- B MEDIA: MediaCard.tsx (branded card: 14px radius, 2px colors.primary border (#0B4F6C —
  app's actual brand primary used instead of the suggested #3A5DAE for palette consistency),
  shadow, HogoPlus eye badge bottom-right, expand pill TOP-LEFT to avoid the status chip) +
  MediaViewerModal (photo pinch-zoom ScrollView / video expo-video nativeControls).
  Used in: incident/[id] main media + resolution photo, ReadOnlyField photo case (submission
  detail), approvals selfies + face-compare (Pressable → shared MediaViewerModal).
  Old IncidentVideo inline player + ReadOnlyField's own modal removed.
- D FOOTER: BrandFooter.tsx — maroon #7A1F2B, 36px + safe-area, untinted eye logo in a white
  chip + "HogoPlus-FS". On: language, phone, otp, pending, incident/success, form/success.
  NOT on tab screens/camera/viewers. Webdash: .brand-footer band + .result-media branded card
  + .media-brand-pill in incident modal (MUST import eyeBase in Department.tsx — vite build
  does NOT typecheck; a missing import crashed the modal at runtime once).
- Tests: 158/158 pytest, i18n parity 329/329/329 keys. E2 iteration_15.json ALL PASS.
- LESSON: apt-installed test infra (postgres/redis/pgvector) VANISHES between sessions —
  reinstall per runbook: apt postgresql redis-server postgresql-server-dev-15 build-essential,
  build pgvector v0.8.0 from source, CREATE ROLE hogo + db hogoplus_test + EXTENSION vector.
- Untested (needs device/build): video full-screen viewer with a real video incident,
  pull-to-refresh gesture (native-only). v1.0.3 build next.

## Prompt 14 — DEMO SHOWCASE BUBBLE (2026-06) ✅ COMPLETE
- `is_demo` on employees + 7 data tables, `is_demo_seed` on the 7 data tables (migration 0008, applied to Neon prod).
- Write tagging: incidents, form_submissions, attendance, shift_swaps, chat_messages set is_demo from creator; notifications inherit recipient class (app/notify.py); audit_events inherit actor class (app/audit.py).
- Read isolation: ALL lists/details/aggregates in incidents.py, forms.py, attendance.py, shifts.py, dashboard.py (overview, dept detail, approvals aging, plate search, audit trail, reports list), admin.py (employee search, pending) filter by viewer's is_demo. AI usage counters split (ai:usage:demo:* keys). Nightly report + escalation sweep + face-mismatch routing are class-aware (app/demo.py resolve_dept_manager_id / get_role_holder).
- Demo cast: 28 accounts (+919000000001..013 workers, ..101..113 managers, 500 CGM, 600 MD), seeded via scripts/seed_demo_cast.py. Login: fixed OTP 123456 driven by is_demo flag (env whitelist kept for 2 real admin numbers). Demo numbers NEVER receive SMS.
- Showcase seed (scripts/seed_demo_showcase.py): 14 form submissions (PURCHASE approved indent w/ trail, STORE pending, ENGINEERING rejected+approved, CANE_YARD plate MH16AB1234, etc), 7 incidents (submitted/seen/in_progress/resolved+photo/escalated critical), 18 attendance rows (1 flagged), R2 photos under demo-seed-* keys. All is_demo_seed=true.
- Cleanup: scheduler job demo_cleanup_sweep (every 15 min) purges is_demo & !is_demo_seed rows older than 60 min incl. R2 media (app/demo_cleanup.py). POST /api/admin/purge-demo-data {dry_run, include_seed} — real CGM/MD only.
- ALLOW_NEW_REGISTRATION env (default true): false blocks OTP for unknown numbers with trilingual 403 (mobile phone.tsx shows localized message). User sets false in Deployment Secrets during contest.
- Demo users cannot mutate shared config (settings, beacons, forms, SOPs, test-sms, reports, backup) — require_real_role.
- Tests: 158 → 170 (tests/test_demo_isolation.py: cross-bubble, dept-scoping, scheduler/report exclusion, mocked-clock cleanup, login matrix, purge, shared-config guard).
- Webdash demo logins: D500/Demo@7547 (CGM), D600/Demo@1751 (MD).

## Prompt 15 — enriched demo showcase seed (2026-06) ✅ COMPLETE
- seed_demo_showcase.py now seeds: 17 incidents covering ALL 13 depts (dept-appropriate Marathi/English content, photos on all, WAV voice notes on 3, plate MH16AB1234 on CANE_YARD, 2 resolved w/ photo, 1 escalated critical), 5 shift swaps (2 pending_target / 2 pending_manager / 1 approved) between same-dept demo workers (added 4 "Worker 2" accounts D021-D024), 1 pending registration (D700), 40 matching notifications, 14 submissions, 18 attendance rows — all is_demo=true AND is_demo_seed=true.
- Verified live: Demo CGM overview shows 15 open complaints / 22 pending across all 13 tiles; approvals mix = 6 submissions + 11 incidents + 4 swaps + 1 registration; Demo ENG Manager sees only ENG items; real CGM counts unchanged (32 open / 397 total); 0 non-seed demo rows (cleanup-proof).

## Prompt 16 — Delight & Polish Pass (2026-06) ✅ (ships in v1.0.7)
Worker: time-of-day greeting + today strip (home), attendance streak chip (home + punch result), 0.6s tick pop animation on punch result, digital ID card w/ QR + share (app/id-card.tsx, react-native-qrcode-svg + view-shot + expo-sharing), one-time camera coach overlay (AsyncStorage hogo.coach.incidentCamera), voice-check hint above form Submit when AI-filled.
Manager/MD: manager morning card on home (rank≤3, taps → Approvals), 24h+ aging chips in mobile Approvals, Factory Pulse AI sentence on webdash Overview (GET /api/dashboard/pulse, redis-cached 10 min per class+lang, static fallback, class-isolated).
App-wide: trilingual timeAgo() relative timestamps (alerts/reports/approvals), update banner (GET /api/app-version + PUT /api/admin/app-version + app_versions table, migration 0009; checks once/day, dismissible), OfflineStrip via NetInfo in root layout, Sahayak starter chips (4 tappable questions), warm empty states + micro-copy pass ×3 languages (i18n parity 359 keys each).
SKIPPED: Android app shortcuts (needs expo-quick-actions native module — untestable in Expo Go, build risk); attendance deep-link chip in Sahayak (chat-only chips kept).
Tests: 170 → 173 (tests/test_prompt16.py). useCachedFetch now supports {enabled}. App-version row set to 1.0.7 in prod DB.

## Prompt 17 — Onboarding + Access Mgmt + Face Enroll + Guards + Push/Escalation/Announcements (2026-06) ✅ code complete (ships in v1.0.8 — DO NOT auto-deploy; owner decides post-launch)
- Part A (live earlier): emp 0428 Pathan Irfan Husen → Manager/TIME_OFFICE (verified in prod Neon).
  Propagation: role is read from DB per request; mobile refreshes profile on hydrate AND on every
  app-foreground (usePushSetup AppState hook) — Time Office queues appear on next app open, no re-login.
- Part B backend: POST /api/admin/employees (direct-add, active immediately + welcome notif + GEN/chosen
  shift baseline), GET /api/admin/emp-id-suggest, PATCH /api/admin/employees/{id} guardrails (Time Office
  cannot touch Manager+ accounts nor grant Manager+ roles; CGM/MD can), GET /api/admin/employees search
  opened to Time Office mgr (_require_time_office_or_top). Mobile: home tile "Employees" (TO/CGM/MD) →
  app/employees/index (debounced search) + new.tsx (direct-add w/ suggested emp_id) + edit.tsx (PATCH only
  changed fields; shift default KEEP). Shared src/components/EmployeeForm.tsx.
- Part C face enroll: POST /api/employees/me/face-enroll {selfie_key} — reuses EXISTING reference bootstrap
  fields; 409 if reference exists; notifies TIME_OFFICE manager (type face_enrolled); reset-reference-selfie
  = reject path. employee_profile now has has_face_reference. Mobile: app/face-enroll.tsx (intro → SelfieCamera
  → upload → enroll), gated in index.tsx (native only, has_face_reference===false strict, once per install
  hogo.faceEnrollAsked, skippable "नंतर करा"). Punch verification path UNTOUCHED.
- Part D guards: src/components/CaptureGuards.tsx — camera/location perms + GPS-services + Bluetooth radio
  pre-capture checklist (AppState recheck, latch once passed, camera hard / rest soft w/ Continue anyway,
  Location.enableNetworkProviderAsync on Android, openSettings for blocked). Wrapped: punch.tsx (all 4),
  capture.tsx (location+gps — camera UI already in-screen). BleScanner.getBleState() added.
- Part E push: notify.py ExpoPushSender live (NoopPushSender under TESTING); dispatcher mirrors every in-app
  notification as push in recipient's language via employees.expo_push_token (column pre-existed).
  Frontend: safeNotifications.ts extended (registerPushTokenSafe/tap listener/foreground handler — all lazy,
  Expo Go/web = no-op), usePushSetup() in root _layout: registers token → PATCH /employees/me, deep-links
  push taps to incident/[id] or alerts, foreground profile refresh. PUSH DELIVERY ONLY TESTABLE ON BUILT APK.
- Part E escalation: POST /api/incidents/{id}/escalate {mode: department|employee, reason req} — handling
  manager/CGM/MD only; department → dept manager (CGM fallback), employee → rank≤3 target only; sets
  status=escalated + escalated_to/at + timeline(manual:true) + notify target & reporter + audit. GET
  /api/incidents/escalation-targets (rank≤3). Mobile: Escalate button (incident detail manager actions) →
  EscalateModal (dept chips / person search + reason).
- Part F announcements: POST /api/admin/announcements {title, message, audience all|department} — manager →
  own dept only; CGM/MD → any dept or all; fanout = dispatcher.notify per active approved same-bubble
  employee (excl. sender, phone NOT NULL) → in-app + push; audit announcement.sent. Mobile: home tile
  "Announcement" (rank≤3) → app/announce.tsx composer (dept chips + All for rank≤2).
- i18n: 359 → 420 keys ×3 (face/guard/escalate/announce/emp namespaces), parity GREEN.
- Tests: 173 → 183 (tests/test_prompt17.py: direct-add, role guardrails, patch guardrails, propagation
  without re-login, TO search access, escalate dept+employee+403/422/409, targets, announcement scoping,
  push-mirror-token recorder test, face enroll flow incl. reset). Local test infra reinstalled this fork
  (apt PG15+redis, pgvector v0.8.0 from source).
- LESSON: a search_replace batch dropped the @router.get("/incidents/{incident_id}") decorator (route
  vanished, 11 tests failed) — always run the FULL suite after router edits.

## Prompt 18 — MD Dashboard Simplify + Speed + Launch-Eve Test Sweep (2026-06) ✅ (webdash+backend only; mobile FROZEN)
Part A (shipped-ready, re-publish required):
- Webdash: NEW landing = Incidents feed (src/screens/Incidents.tsx, route "/"): open-critical pinned first + newest,
  photo/video thumbnails (lazy), severity chips, time-ago, plate chips, detail modal, server search q (plate/category/
  dept/reporter/description), first 20 + infinite scroll, localStorage SWR cache-first (src/swr.ts), skeletons.
- Overview.tsx → "Departments" second tab (/departments): KPIs + tiles + chart + pulse; live-incident column removed.
- Vehicles screen DELETED (nav+route+i18n keys plateSearchHint/searchBtn/results/noPlateResults/t_incident/t_submission/
  nav_vehicles); plate search lives as filter on incidents list. Backend /dashboard/plates/search kept (unused, harmless).
- Nav minimal: Complaints · Departments · Approvals · Reports · Admin + "More ▾"(Attendance). Renames: Overview→Departments,
  "Reports & AI"→Reports. Base font 17px, sidebar 17px.
- Backend speed (Neon RTT ~425ms/query was the killer): Employee.role/department lazy selectin→joined (3→1 auth round
  trips, EVERY request −0.85s); dashboard overview 10 aggregate queries now run CONCURRENTLY (asyncio.gather, own sessions)
  + in-process 45s TTL cache + 15s background warmer in main.py (both classes, unscoped) → overview 4.2-8.9s → 0.63-0.85s;
  NEW GET /dashboard/incidents-feed (offset/limit/q, crit-first stable order); GZipMiddleware (17.4KB→4KB);
  R2 presign 1h in-process cache in storage.py (60 signs/feed was ~2s); pool: pre_ping OFF + recycle 280 + size 40/overflow
  110/timeout 45 (load test exhausted 10+20 → 500s).
- Timings after: auth/me 1.89→0.64-0.85s, overview→0.63-0.85s warm-cached (always warm via warmer), feed ~1.2-1.5s warm
  (first-ever call ~4s while presigns cache), login→rows-visible ~3.3s incl OTP verify; warm tab switches 29ms-1.3s.
Part B sweep results (see final report in chat): B1 matrix 106/108 checks PASS across all 13 depts (2 "fails" were
test-script artifacts — server correctly validated form fields); punch idempotency 409 ✓; swap lifecycle approved ✓
(PRODUCTION; other depts lacked different-shift candidates — data condition); registration E2E ✓ then real-bubble test
row deleted, ALLOW_NEW_REGISTRATION reverted to false; load: 300 VU/230s → 4853 req, 0 server 5xx, 0.14% client timeouts
(fixed from 10.6% 5xx by pool sizing), RSS ~390MB peak (1Gi ok); scheduler 6 jobs registered ✓; R2 backup today 105KB,
dump contains 1705 INSERT rows ✓; demo isolation PERFECT (real counts 403/35/8/1/88 unchanged after full assault).
v1.0.8 list: POST /incidents idempotency client_ref (dup risk on network retry), wrong-OTP inline error visibility on
device, device-only QA (hardware back, airplane-mode outbox, app-kill, voice-fill live audio, BLE), swap candidates
seeding for more demo depts.
DO NOT DEPLOY without owner's go — launch day runs current build; re-publish ships Part A when owner decides.

## Prompt 21 (2026-07-25) — PRE-LAUNCH BUG TRIAGE (diagnosis-first; fixes for Bugs 2/3/4 HELD)
User rule: NO fixes until diagnosis approved, EXCEPT pre-approved list (all DONE + verified):
- config.py: otp_mode default "" (was "demo"), demo_otp_enabled default False (was True) → demo OTP
  acceptance now impossible unless DEMO_OTP_ENABLED explicitly true. Env-hygiene sanitizer
  (field_validator "*", before): strips whitespace/outer quotes; inline " #comment" stripped for simple
  fields only (never OTP_TEMPLATE_TEXT/secrets/URLs); empty value on bool/int fields → default.
  New settings: otp_max_per_window=5, otp_window_minutes=10, otp_resend_cooldown_seconds=45.
- main.py startup: FAIL-FAST guard (RuntimeError OTP_MODE_NOT_SET / OTP_MODE_INVALID /
  SMSGATEWAYHUB_CONFIG_MISSING / OTP_TEMPLATE_TEXT_INVALID; WARN when ENTITY_ID blank) + one boot
  INFO line "OTP CONFIG: mode=... demo_otp_enabled=... api_key=masked ... rate_limit=5/10min cooldown=45s".
- auth.py send-otp: cooldown key otp:cooldown:{phone} (45s) + window otp:send:{phone} (5/10min);
  429 detail = {code:"otp_rate_limited", retry_after_seconds, en/hi/mr}; success returns resend_after.
- otp.py: mask_phone/mask_key; SMSGatewayHub send_raw logs RAW http status+body+message id (API key
  masked, OTP never logged in prod path); demo fallback on gateway failure REMOVED (raises 502).
- scripts/test_sms.py (host, stdlib-only): .env LINT (BOM/CRLF/unbalanced quotes/inline comments/
  concat-keys/dup keys) + effective OTP config + --send +91X real gateway call printing raw response.
- App: phone.tsx/otp.tsx show localized wait message from 429 detail (localizedDetail helper in
  client.ts); otp.tsx RESEND_SECONDS 30→45. Tests: rate-limit test now 5→429; conftest cooldown=0.
- Verified E2E on sandbox: boot line OK, 5 sends then 429 (retry_after=582), cooldown 429 (43s, trilingual),
  demo login intact, fail-fast fires when OTP_MODE missing. SMSGatewayHub docs confirm EntityId (DLT PE ID)
  IS required for India DLT traffic — currently blank in .env.
DIAGNOSIS EVIDENCE (for report): Bug1 = host .env values not reaching container (user: printenv OTP_MODE
empty) + old silent demo defaults; SECURITY HOLE PROVEN: logged in as real CGM (+918483029039) with 123456
(whitelist + demo_otp_enabled). Bug2 = backend registration chain PROVEN healthy (403 guard, upload with
registration token 200, Rekognition gate 400 no_face); app-side/misleading-error suspected; needs user's
on-device symptom. Bug3 = CaptureGuards soft-gates by design ("Continue anyway", getBleState 'unknown'→pass);
backend accepts GPS-less punch as flagged/gps_missing. Bug4 = escalate API works (200 employee-mode);
dept-mode 409 for 7 manager-less depts when CGM escalates (fallback target = self); error toasts inside RN
Modal are INVISIBLE on Android (ToastHost under native modal window) → "does nothing".
Bugs 2/3/4 fixes: HELD pending user approval of diagnosis.

## Prompt 21 (contd) — Approved fixes + Time Office role management (2026-07)
- Bug 4 SHIPPED (backend): escalate dept-mode fallback dept-mgr→CGM→MD, never caller; trilingual 409
  no_escalation_target. Verified live: previously-409 dept escalate now 200. EscalateModal (v1.0.10):
  errors render INSIDE the sheet (testID escalate-error) via localizedDetail; list-load failures surfaced.
- Bug 3 SHIPPED (app, v1.0.10): CaptureGuards strict prop (punch flow only): no Continue-anyway for
  location/gps/bluetooth; BLE off/unknown blocks on real builds (getBleScanner().isReal); 3s poll + AppState
  recheck; guard.strictBody i18n en/hi/mr. Backend 422 for GPS-less punches HELD (still flagged) per user.
- Bug 2 SHIPPED (app, v1.0.10): SelfieCamera hardening — auto-request undetermined permission on mount,
  ActivityIndicator instead of black !permission view, CameraView onMountError + 6s onCameraReady watchdog
  (native only) → trilingual errors.cameraStart + Retry (remount via key) + Open Settings. User's device
  discriminator answer still pending (pure-black vs permission card).
- TIME OFFICE ROLE MANAGEMENT (new req, SHIPPED): patch_employee + direct_add rails relaxed rank<=3→rank<=2
  (TO may grant/edit Manager, never CGM/MD, both directions); assign-manager endpoint opened to
  _require_time_office_or_top with rails: demo actors 403 (shared table), TO-installed HOD must hold Manager
  role, target must be real+active; all audited (employee.updated / department.assign_manager). App:
  EmployeeForm Manager chip for TO; employees/edit 'Set as HOD' button (emp-make-hod-button) for Manager
  accounts. Tests updated: test_prompt17 (direct-add + patch guardrails), test_admin_misc (assign-manager TO
  cases), live_prompt17_api (grant-manager-allowed, cgm-forbidden). Verified live 6/6 rails + testing agent
  iteration_17 ALL UI FLOWS PASS.
- NOTE (intentional): frontend/.env EXPO_PUBLIC_API_URL points to the Mumbai custom domain for device builds —
  web-preview demo logins 401 against it; testing agent temporarily flips to preview URL and reverts.
- Manager-less departments (user assigning interim HODs via webdash): ACCOUNTS, AGRICULTURE, CANE_YARD,
  CIVIL, DISTILLERY, GODOWN, STORE.

## QA Campaign close-out (2026-07-26 night, pre-launch freeze)
- LAST backend change before freeze: incidents-feed search 500 fixed (enum→String cast for ILIKE),
  commit 7e7c612; verified 200 on plate/text/dept/no-q searches against Neon.
- Webdash FULL UI pass done (all 8 views + Marathi toggle + detail modal) — screenshots delivered.
- Nightly PDF Devanagari verified (mr/hi generated locally from prod data; shaping correct).
- cleanup_prelaunch.py HELD for explicit "RUN CLEANUP" (runs on EC2:
  `docker compose exec backend python scripts/cleanup_prelaunch.py --execute`, or from sandbox vs Neon).
- Deferred to post-launch per user: shift-swap SELECT..FOR UPDATE, outbox idempotency,
  .dockerignore destructive scripts, full-decode upload validation, GET /admin/employees/{id}.

## Field failure fix-pack (launch eve, 2026-07-28)
- Beacon registry: 6 real iBeacons (uuid 01122334-...-eff0, major 1, minors 33/18/7/34/4/15).
- Geofence now 19.313483/74.709384/1200m (user-applied).
- BEACON WINS ladder live on EC2. v1.0.11 (10011) ready: neverForLocation removed, LowLatency
  10s early-exit scan, fail-closed Nearby-devices gate, incident strict guard, zone tag E2E.
- Ghost-reference hardening + reset-reference-selfie endpoint = recovery paths for lost R2 refs.
- Pending user actions: deploy 2a407ed/f80b1f4 backend pack; build v1.0.11 via Publish (AAB for
  Play with PEPK existing-key setup BEFORE first upload); field protocol in STAGE3_v1.0.11_TEST_PLAN.md;
  reject 4 flagged rows; clear refs 0001/1212 (curl reset-reference-selfie); then RUN CLEANUP.

## Launch-day Tasks A/B/C — full beacon registry + beacon-first flag (2026-06 fork) ✅
- TASK C ROOT CAUSE (user suspicion CONFIRMED): registry held only the 6 OUTDOOR minors
  (33/18/7/34/4/15); v1.0.14 scanner matches ONLY registry entries (BleScanner.ts L96-99 set build,
  L126-133 silent skip of unregistered, L99 empty-registry instant null) → all 23 indoor beacons
  invisible → punches stored ble_beacon_id=NULL. DATA-ONLY FIX (Task A). Server evidence: only 2 real
  punches existed on 2026-07-29 (0001 Amey, 1212 Yema — both beacon EMPTY, flagged reference_bootstrap);
  the other claimed ~15 punches never reached the server (only 10 real logins since 27th).
- TASK A DONE (production, api.hogoplus.in): bulk-imported 23 indoor iBeacons (shared UUID
  01122334-4556-6778-899A-ABBCCDDEEFF0, major 1) → 29 total active zones; hi/mr labels PATCHed on the
  23 new rows (6 originals untouched). MINOR 0 = Civil verified SAFE end-to-end (all checks use
  `is not None` / string set keys); live prod demo punch with minor 0 → verified_plus zone Civil.
  Resolver proof for all 23 minors + negative controls (999, 6, wrong-major). Mobile fetches
  /attendance/beacon-registry fresh on every punch (punch.tsx L63-68) → NO REBUILD NEEDED.
  Evidence scripts: scripts/taska_register_beacons.py / taska_resolver_proof.py / taska_minor0_e2e.py /
  taskc_evidence.py.
- TASK B SHIPPED (backend+webdash, flag DEFAULT OFF — byte-identical when off): migration 0011 adds
  settings.beacon_first_mode (applied to Neon; old EC2 code ignores the column). Punch ladder
  (attendance.py): flag ON → beacon match = verified_plus (unchanged); NO beacon = ACCEPTED but
  flagged no_beacon_gps_only / no_beacon_no_gps; geofence never gates (gps_verified still stored as
  evidence). Incidents NEVER blocked/flagged for beacon (already true; zone display already prominent
  on webdash feed/modals + mobile detail — zone > address > coords). Admin GET/PATCH /settings expose
  the flag; webdash Admin geofence card got a "Beacon-first attendance" checkbox (rebuilt to
  webdash_dist). Tests 210/210 (test_beacon_first.py: 6-case matrix ×ON/OFF + incident non-block +
  settings roundtrip). Live demo-side matrix run on prod DB in both flag states
  (scripts/taskb_live_matrix.py), flag reverted OFF after.
- APP-SIDE: NOTHING requires a new APK. v1.0.15 batch (cosmetic only): i18n strings for the two new
  flag reasons (mobile Time Office queue shows the raw readable string until then).
- NOT COMMITTED to git (privacy.html conflict branch conflict_280726_2331 still unresolved — sync
  main before any Save to GitHub).
- Test infra reinstalled this fork (apt PG15+redis, pgvector v0.8.0 from source, role hogo,
  hogoplus_test + vector ext).

## v1.0.15 — neverForLocation ARTIFACT root cause + batch (2026-06 fork) ✅ code complete, build pending
- TRUE ROOT CAUSE of all beacon failures (user's APK autopsy: BLUETOOTH_SCAN usesPermissionFlags=
  0x00010000 in the v1.0.14 artifact; versionCode 133 ≠ app.json 10014 proving pipeline overrides):
  react-native-ble-plx's LIBRARY AndroidManifest.xml (in the AAR) declares BLUETOOTH_SCAN with
  neverForLocation; the GRADLE MANIFEST MERGER re-injects it into every artifact AFTER prebuild —
  repo/app.json fixes can never win, and prebuild-output checks look clean while artifacts are dirty.
  With that flag the OS strips ALL iBeacon frames before the app sees them.
- FIX (merge-time authority): local config plugin frontend/plugins/withBleScanNoNeverForLocation.js
  (LAST in app.json plugins) stamps tools:remove="android:usesPermissionFlags" onto the app
  manifest's BLUETOOTH_SCAN + ensures xmlns:tools. Manifest merger MUST strip the attr regardless
  of library contributions; every pipeline prebuild re-applies the stamp. VERIFIED via prebuild in
  /tmp copy: `<uses-permission android:name="android.permission.BLUETOOTH_SCAN"
  tools:remove="android:usesPermissionFlags"/>`. ACCESS_FINE_LOCATION requirement (needed without
  the flag) already satisfied: manifest has it (expo-location) + strict guards force grant+GPS-ON
  pre-scan. app.json: version 1.0.15, versionCode 10015 (pipeline will assign its own >133).
- v1.0.15 batch (all shipped in repo): Approvals→Attendance REJECT button (att-reject-<id>,
  paired with approve, optimistic, POST /attendance/{id}/reject); flag-reason i18n
  att.reasonNoBeacon/att.reasonNoBeaconNoGps ×3 (parity 430 keys); incident capture live zone chip
  (testID zone-chip, native only) fed by enriched GET /attendance/beacon-registry (entries now carry
  zone_en/hi/mr + macs_detail — additive, old builds ignore; backend half deployable NOW);
  SelfieCamera styles.center pre-existing tsc error fixed.
- Tests: pytest 211/211; tsc clean; eslint clean; testing_agent iteration_19 ALL PASS (reject flow
  E2E with live no_beacon_gps_only rows in en+mr, no key leaks, capture web regression).
  beacon_first_mode verified False after tests; frontend/.env restored to api.hogoplus.in.
- USER ARTIFACT AUTOPSY before install: aapt2 dump xmltree (BLUETOOTH_SCAN must have NO
  usesPermissionFlags), aapt2 dump badging (versionCode >133, versionName 1.0.15), strings on
  assets/index.android.bundle (api.hogoplus.in pinned, no preview/localhost).

## v1.0.16 — TRUE ROOT CAUSE + FIELD INSTRUMENTATION (2026-06 fork) ✅ code complete, build pending
- v1.0.15 artifact verified CLEAN by user (no usesPermissionFlags, versionCode 135, correct API
  base) yet detection still failed with beacon in hand. TRUE BUG FOUND with code evidence:
  react-native-ble-plx 3.5.1 Android AdvertisementData.parseManufacturerData (L200-204) keeps ONE
  manufacturerData field and OVERWRITES it for EVERY 0xFF AD structure in the merged ADV+SCAN_RSP
  record. Vendor beacons (SmartConfig-configurable) interleave a vendor config frame in the scan
  response → it clobbers the Apple 4C 00 02 15 frame → the app's header-anchored parseIBeacon saw
  only the vendor frame → null → no match ever, on every beacon, every version.
- FIX: new pure module src/ble/ibeaconParse.ts — extractIBeacons() signature-scans
  device.rawScanRecord (full merged record, exposed by ble-plx) for 4C 00 02 15 at ANY offset,
  returns ALL frames; ibKey() lowercases uuid + Number-coerces major/minor. BleScanner.scan uses
  rawScanRecord+manufacturerData candidates. User hypotheses (a) case (b) type (c) uuid-format
  ELIMINATED via unit test frontend/scripts/test-ibeacon-parse.js (16/16 incl. repro of old
  parser failing on vendor-clobbered payload while new extractor recovers from rawScanRecord).
- Permission hardening: requestBlePermissions/checkBlePermissions on Android 12+ now also
  require+request ACCESS_FINE_LOCATION (mandatory for scan results once neverForLocation is
  removed; an "approximate-only" location grant silently yields zero scan results). Punch flow
  remains fail-closed (punch.tsx L74-82 aborts w/ toast on denied/blocked).
- INSTRUMENTATION (temporary): hidden BLE Diagnostics screen app/ble-diag.tsx — entry: LONG-PRESS
  the avatar on Profile tab (600ms). Shows permissions/radio/location-services, fetched registry
  (29 entries), 15s diagnostic scan (allowDuplicates ON, frames merged per device) with parsed
  iBeacon candidates + per-candidate verdict (matched/uuid_mismatch/major_mismatch/
  minor_not_registered/no_ibeacon_frame/no_mfg_data), and "Send report to server".
  Backend: POST /api/attendance/ble-diag (audit action ble.diag, 150KB cap, 413 oversize),
  GET /api/admin/ble-diag?limit= (CGM/MD rank<=2). scanDiagnostics() added to BleScanner.
- app.json 1.0.16/10016. pytest 214/214 (tests/test_ble_diag.py new), tsc clean, eslint clean,
  E2E roundtrip on live DB (demo D002 report → CGM read), web smoke: diag screen renders 29-entry
  registry. frontend/.env restored to api.hogoplus.in.
- NOTE: test infra (PG15/redis/pgvector) was wiped again by pod reset and reinstalled.

## v1.0.17 — SPEED PACK + incident zone + Play in-app updates (2026-06 fork) ✅ code complete, build pending
- ITEM 1 (speed): v1.0.16 punch was fully SEQUENTIAL after the selfie (GPS≤8s → geocode → registry
  RTT → perm → 10s scan → compress → upload → submit ≈ 60s field-observed). NEW: shared
  src/ble/zoneSession.ts — pre-warms scan at screen OPEN, registry cached (AsyncStorage 10-min TTL,
  bg refresh, stale-if-offline), successive 5s LOW_LATENCY windows ≤60s w/ early exit, singleton
  (serialized stopDeviceScan). punch.tsx: GPS|compress+upload|zone(≤5s cap)|geocode(≤3s, display-only)
  all PARALLEL; per-stage timings stored → shown in BLE Diagnostics "Last punch timing breakdown"
  + included in diag report. LATE ATTACH: POST /api/attendance/{id}/attach-beacon (self-only,
  15-min window, idempotent, beacon wins over location outcomes ONLY — face flags + reviewed rows
  untouched) called automatically when match lands post-submit.
- ITEM 2 (incident zone): root cause = single mount-time 10s window competing with camera init,
  never retried. Now uses the EXACT same ZoneSession (chip subscribes via onUpdate). Zone shown:
  capture chip, app detail, webdash feed/modals/department (already), nightly PDF critical list
  (added "— 📍 zone"). Backend halves deployable now.
- ITEM 3 (performance): measured — hot API payloads all ≤2.2KB; latency is RTT-bound per request;
  selfie 720px/q0.7 ≈80-150KB; incident photo 1600px/q0.7 ≈300-500KB (already compressed);
  remaining candidates: video (uncompressed, up to tens of MB) and on-device cold-start (needs
  device numbers — timing card now provides punch numbers).
- ITEM 4 (in-app updates): sp-react-native-in-app-updates@2 + react-native-device-info@15 installed
  (autolink at prebuild). UpdateGate in root layout: backend GET /app-version drives it — flexible
  by default, IMMEDIATE when force_update=true (migration 0012, applied to Neon; PUT
  /admin/app-version now accepts force_update). Sideload/Expo Go/web fail OPEN → existing
  UpdateBanner fallback. TESTING AGENT P0 FIX (keep!): UpdateGate.web.tsx stub — metro statically
  resolves native-only require on web, stub prevents blank web bundle.
- app.json 1.0.17/10017. pytest 218/218 (test_attach_beacon.py new, prompt16 updated for
  force_update); iter20 frontend E2E PASS (punch ~6s on web, incident, /ble-diag, attach-beacon).
- Prod app-version row still "1.0.7" — in-app update fires only when row bumped above installed
  version AND a higher build is live on the same Play track. Play Console: no extra config; app
  must be installed VIA Play.

## v1.0.18 batch (2026-06 fork) — keyboard overlap + prod DB task + self-reg validation
- TASK 1 (prod DB): employee 0061 Sunil Kondiram Vavhal phone updated in LIVE Neon DB
  +917020792694 → +917020892694 (dup-checked: none; format matches PHONE_REGEX; send-otp
  resolution dry-checked; no redis locks). seed_employees.csv row updated to match — seed.py is
  INSERT-ONLY (skips existing emp_ids), so GitHub seed edits can NEVER drift/overwrite live rows.
- TASK 2 (keyboard, THE v1.0.18 build): app-wide migration to react-native-keyboard-controller
  1.18.5 (SDK 54). KeyboardProvider in root _layout. KeyboardAwareScrollView (bottomOffset 24) on:
  phone, otp, register-name, announce, swap/new, incident/[id], incident/capture preview,
  EmployeeForm, FormRenderer (kept scrollRef/scrollToFirstError). RNKC KeyboardAvoidingView
  behavior="padding" inside Modals: EscalateModal sheet, submission/[id] reject, approvals reject.
  sahayak chat = behavior="translate-with-padding". employees list: keyboardDismissMode="on-drag".
  RNKC is NATIVE-ONLY (web no-op) → real avoidance verifiable only on the APK; web regression
  sweep all-PASS (login, sahayak, announce, employees+form, swap, incident detail, escalate modal,
  forms engine text field). app.json bumped 1.0.18/10018.
- TASK 3 (self-reg E2E): VALIDATED against live stack (ALLOW_NEW_REGISTRATION=true in backend/.env):
  unknown number → send-otp 200 → verify-otp is_new+reg-token → selfie upload (reg token) →
  Rekognition face gate LIVE (rejected pixel image, passed real portrait) → register →
  pending_approval + auto emp_id → re-login lands pending → CGM sees registrant in
  /admin/employees/pending with selfie. Test row fully cleaned from prod DB.
  Repeatable script: backend/scripts/selfreg_e2e.py.
- FINDING: real employees with garbage emp_ids poison auto-ID: 3003200 "Haru", 300319 "Shubham",
  300312 "Karan" (is_demo=false) → next self-reg emp_id becomes 3003201 and suggested_emp_id
  3003202. Needs user decision (fix rows or change suggestion query).
- TASK 4 (perf profile, REPORT ONLY per user): /app/docs/PERF_PROFILE_v1.0.17.md — smoking gun:
  backend↔Neon(ap-southeast-1) = 217ms/query, Redis 215ms/op → every request pays RTT × query
  count (incidents 2.7s ≈ 12 RTTs vs dashboard/summary 123ms). Payloads tiny (≤5.4KB). Bundle
  5.66MB/3906 modules. Video 720p/30s no bitrate cap = dominant upload. Fixes proposed for
  v1.0.19 (LIMIT on /incidents, pending-query optimization, region co-location, videoBitrate).
- frontend/.env EXPO_PUBLIC_BACKEND_URL restored to api.hogoplus.in for the build.
- NOTE: backend/.env ALLOW_NEW_REGISTRATION left "true" (validated state). Deployed backend env
  is controlled via Deployment Secrets — user must set it true there for Play Store users.

## v1.0.19 QUEUE (user-approved 2026-06, DO NOT build until user green-lights)
1. emp_id suggestion query: IGNORE outlier ids (300312/300319/3003200 stay as-is — history
   references them; do NOT renumber rows). Suggest next free id from the normal 4-digit range
   (e.g. max emp_id where length=4 / value < 10000, excluding demo).
2. One-tap "Share diagnostics": post the punch timing card to POST /api/attendance/ble-diag
   automatically from the timing card UI (approved — factory numbers without screenshots).
3. Perf app-side: /incidents LIMIT+pagination (backend), video bitrate cap (~2 Mbps) on
   incident recording, /departments client cache, parallel auth-hydration storage reads.
4. OTP IP-level rate limiting per /app/docs/OTP_IP_RATE_LIMIT_DESIGN.md (shadow mode first).
5. DB migration Neon SG → Mumbai: user executes separately per
   /app/docs/DB_MIGRATION_PLAN_MUMBAI.md (WRITTEN PLAN ONLY, pre-flight = confirm backend region).

## TESTING POLICY (user directive 2026-06 — PERMANENT)
- NEVER use +918483029039 (user's personal number) in automated tests again.
- Automated tests use the sealed demo bubble: CGM D500 +919000000500, Worker D001 +919000000001
  (fixed OTP 123456, is_demo, no SMS ever). Real-account path when needed: 0021 +917972540971
  (permanent Play-reviewer whitelist account). Unknown-number/registration tests: +91999990001x
  range (verified no employee rows).

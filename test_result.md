#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

# THIS SECTION CONTAINS CRITICAL TESTING INSTRUCTIONS FOR BOTH AGENTS
# BOTH MAIN_AGENT AND TESTING_AGENT MUST PRESERVE THIS ENTIRE BLOCK

# Communication Protocol:
# If the `testing_agent` is available, main agent should delegate all testing tasks to it.
#
# You have access to a file called `test_result.md`. This file contains the complete testing state
# and history, and is the primary means of communication between main and the testing agent.
#
# Main and testing agents must follow this exact format to maintain testing data. 
# The testing data must be entered in yaml format Below is the data structure:
# 
## user_problem_statement: {problem_statement}
## backend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.py"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## frontend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.js"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## metadata:
##   created_by: "main_agent"
##   version: "1.0"
##   test_sequence: 0
##   run_ui: false
##
## test_plan:
##   current_focus:
##     - "Task name 1"
##     - "Task name 2"
##   stuck_tasks:
##     - "Task name with persistent issues"
##   test_all: false
##   test_priority: "high_first"  # or "sequential" or "stuck_first"
##
## agent_communication:
##     -agent: "main"  # or "testing" or "user"
##     -message: "Communication message between agents"

# Protocol Guidelines for Main agent
#
# 1. Update Test Result File Before Testing:
#    - Main agent must always update the `test_result.md` file before calling the testing agent
#    - Add implementation details to the status_history
#    - Set `needs_retesting` to true for tasks that need testing
#    - Update the `test_plan` section to guide testing priorities
#    - Add a message to `agent_communication` explaining what you've done
#
# 2. Incorporate User Feedback:
#    - When a user provides feedback that something is or isn't working, add this information to the relevant task's status_history
#    - Update the working status based on user feedback
#    - If a user reports an issue with a task that was marked as working, increment the stuck_count
#    - Whenever user reports issue in the app, if we have testing agent and task_result.md file so find the appropriate task for that and append in status_history of that task to contain the user concern and problem as well 
#
# 3. Track Stuck Tasks:
#    - Monitor which tasks have high stuck_count values or where you are fixing same issue again and again, analyze that when you read task_result.md
#    - For persistent issues, use websearch tool to find solutions
#    - Pay special attention to tasks in the stuck_tasks list
#    - When you fix an issue with a stuck task, don't reset the stuck_count until the testing agent confirms it's working
#
# 4. Provide Context to Testing Agent:
#    - When calling the testing agent, provide clear instructions about:
#      - Which tasks need testing (reference the test_plan)
#      - Any authentication details or configuration needed
#      - Specific test scenarios to focus on
#      - Any known issues or edge cases to verify
#
# 5. Call the testing agent with specific instructions referring to test_result.md
#
# IMPORTANT: Main agent must ALWAYS update test_result.md BEFORE calling the testing agent, as it relies on this file to understand what to test next.

#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================



#====================================================================================================
# Testing Data - Main Agent and testing sub agent both should log testing data below this section
#====================================================================================================
## Phase 2 Part 1 — Mobile App (2026-06 fork)
user_problem_statement: Expo mobile app for factory workers (trilingual en/hi/mr, Marathi default).
  Auth (Phone→OTP→Home or Register→Pending), role-aware Home with red incident tile, 3-tap incident
  reporting (category→camera+GPS→watermark burn-in→submit) with offline outbox, attendance punch-in
  (selfie+GPS+BLE→Verified+/Verified/Flagged), notifications, profile, shift screen, EAS config.

frontend:
  - task: "Auth flow (language→phone→OTP→home / register→pending)"
    implemented: true
    working: "NA (smoke-tested login happy path via screenshot: works)"
    files: ["app/(auth)/*.tsx"]
  - task: "Home screen role-aware (worker vs manager tiles, attendance card, punch in/out)"
    implemented: true
    working: "NA (smoke-tested render for worker)"
    files: ["app/(tabs)/home.tsx", "app/(tabs)/_layout.tsx"]
  - task: "Incident 3-tap flow with watermark burn-in + compression + offline outbox"
    implemented: true
    working: "NA"
    files: ["app/incident/category.tsx", "app/incident/capture.tsx", "app/incident/success.tsx", "app/incident/[id].tsx", "src/offline/outbox.ts"]
  - task: "Attendance punch-in (selfie+GPS+BLE) + result + history"
    implemented: true
    working: "NA"
    files: ["app/attendance/punch.tsx", "app/attendance/result.tsx", "app/attendance/history.tsx"]
  - task: "Alerts + Profile (language switcher, logout) + Shift screen"
    implemented: true
    working: "NA"
    files: ["app/(tabs)/alerts.tsx", "app/(tabs)/profile.tsx", "app/shift.tsx"]

backend: unchanged this session (Phase 1 complete, 70 pytest passing)

credentials: see /app/memory/test_credentials.md — demo OTP 123456 for seeded phones.
  Worker: +917972540971 (Khot Mahavir). Manager: +919834705825 (ENGINEERING). CGM: +918483029039.

notes:
  - BLE is a noop scanner on web/Expo Go BY DESIGN (isolated interface) — punch-in will yield "verified" not "verified_plus" in tests; this is expected.
  - Watermark viewshot burn-in is skipped on web (falls back to plain compressed photo) BY DESIGN.
  - File serving GET /api/files/{key} is public; upload requires Bearer token.

## Prompt 6 UX Pack — Mobile Frontend (2026-07 fork)
user_problem_statement: UX Pack mobile UI — photo-first complaint flow (camera opens immediately,
  category defaults 'other', 60s expo-audio voice note), AI category suggestion confirmation card
  post-submit (accept / change → POST /api/incidents/{id}/confirm-routing), Grievance→Complaint
  rename (en/hi/mr), simplified onboarding (Name+Selfie only; Time Office assigns dept/role/emp_id
  on approval), searchable shift-swap colleague picker, mandatory resolution photo on manager
  Resolve, ANPR plate chip (detected_plate) in incident detail + webdash.

frontend:
  - task: "Photo-first complaint capture (camera-first, ✕ close, GPS chip, desc, voice note, submit as 'other')"
    implemented: true
    working: "NA"
    files: ["app/incident/capture.tsx"]
  - task: "Success screen AI suggestion card (poll incident detail; Accept → confirm-routing {}; Change → category+dept modal)"
    implemented: true
    working: "NA"
    files: ["app/incident/success.tsx"]
  - task: "Onboarding simplified: register-name → register-selfie (no department step; register-department.tsx DELETED)"
    implemented: true
    working: "NA"
    files: ["app/(auth)/register-name.tsx", "app/(auth)/register-selfie.tsx"]
  - task: "Approvals regs tab: Approve opens assignment modal (dept list + role chips + emp_id input) → POST /api/admin/employees/{id}/approve with body"
    implemented: true
    working: "NA"
    files: ["app/(tabs)/approvals.tsx"]
  - task: "Shift swap searchable colleague picker (filter by name/emp_id)"
    implemented: true
    working: "NA"
    files: ["app/swap/new.tsx"]
  - task: "Manager Resolve requires resolution photo (PhotoCaptureModal) + resolution photo & detected_plate chip shown in incident detail"
    implemented: true
    working: "NA"
    files: ["app/incident/[id].tsx"]
  - task: "Grievance→Complaint rename trilingual + new UX pack strings (parity verified en/hi/mr)"
    implemented: true
    working: "NA"
    files: ["src/i18n/locales/*.json"]

backend: 126/126 pytest green on Neon/Upstash. Fixed duplicate detect_text def in aws.py +
  extract_plate dict handling in tasks.py. dashboard feed now includes detected_plate.
  ai_timeout path demonstrated live: incident → AI suggestion (water_leakage 0.95) → 11-min
  backdate → sweep → ai_confirmed_by='ai_timeout'. Celery worker restarted (new tasks registered).

credentials: /app/memory/test_credentials.md — demo OTP 123456. Worker +917972540971,
  TIME_OFFICE manager +918308829567, PRODUCTION manager +918379811866, CGM +918483029039.

notes:
  - AI classification is async (celery, ~15-30s). Success screen polls up to ~36s then shows "will route automatically" note.
  - Voice note recording does not work on web preview reliably (expo-audio native); do not fail the flow on web for it.
  - Camera on web preview uses webcam emulation; watermark burn-in skipped on web BY DESIGN.
  - New registrations get department_code NULL until Time Office approval — expected.

## Prompt 7 — VIDEO + PASSWORD LOGIN + POLISH PACK (2026-07 fork)
Part A: Incident camera has photo/video toggle (video max 30s, 720p, expo-camera recordAsync),
  40MB server cap (trilingual 413), mp4/mov upload allowed with ftyp magic check, offline disables
  video toggle (NetInfo), playback via expo-video (mobile) + HTML5 video (webdash feed).
Part B: employees.password_hash + must_change_password; POST /api/admin/employees/{id}/set-password
  (rank<=2 only); POST /api/auth/password-login (emp_id+password, MD/CGM only, redis lockout 5/15min);
  POST /api/auth/change-password; webdash login has OTP/Password tabs + forced-change screen +
  sidebar Change password (top mgmt).
Part C: GET /api/dashboard/plates/search?q= (rank<=3; manager scoped to own dept) + webdash
  Vehicles screen + client-side filter box on Overview live feed.
Part D: address_text on incidents + form_submissions; on-device reverseGeocode at capture time
  (capture.tsx, FormRenderer, punch.tsx); location blocks on incident detail (mobile+dash feed) and
  attendance result (zone > address > coords hierarchy).
Part E: root causes fixed — otp.tsx/pending.tsx now replace to "/" (index gate → primer),
  authStore.hydrate restores hogo.permsPrimed, and re-shows primer ONCE if camera/location still
  undetermined (hogo.permsReprimed guard). acquireGps already requests permission inline (defense in depth).
Backend: 136/136 pytest green (tests/test_prompt7.py added). Live verified: ANPR MH14GH7777 detected
  via real Rekognition on photo-first flow; mp4 presign content-type video/mp4; password login E2E
  (set → temp login → forced change → re-login) done via API and via webdash browser.
Credentials: CGM dashboard password login emp_id 0001 / Hogo@2026Cgm (see memory/test_credentials.md).
NOTE: video recording NOT testable on web preview (expo-camera recordAsync is native-only) — verify
  video capture on device/APK. Do not fail web tests on video recording.

## Prompt 8 — OTP whitelist + BLE-MAC beacons + Android manifest fix (2026-06 fork)
- app.json android.permissions → ["POST_NOTIFICATIONS"] only; all others injected by plugins.
  Verified via expo prebuild sandbox: each <uses-permission> exactly once.
- DEMO_OTP now requires DEMO_OTP_ENABLED + phone in DEMO_OTP_WHITELIST + employee exists.
  Prod whitelist: +918483029039 (CGM), +917972540971 (worker). All other seeded numbers reject 123456.
- ble_beacons.mac_address (unique, AA:BB:CC:DD:EE:FF normalized uppercase, alembic 0006 applied to Neon).
  Beacon CRUD accepts mac_address; duplicate → 409; invalid format → 422.
- GET /api/attendance/beacon-macs (approved employee) → {"macs":[...active registered]}.
- punch-in: sent MAC matched case-insensitively vs registered active beacons; registered → verified_plus
  + backend-resolved ble_zone; unregistered → ignored (verified); no BLE → verified. ble_zone removed
  from punch payload.
- Mobile BleScanner matches device.id (Android MAC) against registered list, strongest RSSI (native-only,
  NOT testable on web preview — noop scanner returns null on web/Expo Go BY DESIGN).
- Webdash Admin: new "📡 BLE beacons" card (add/toggle/delete, MAC format validation).
- Backend: 140/140 pytest green. Prod API verified via curl (whitelist 200/401, beacon-macs, CRUD).

## Prompt 9 — ANPR production fix + result-card UI (2026-06)
- Root cause: prod deploy has no celery worker + silent enqueue failure; fixed via in-process
  FastAPI BackgroundTasks (ANPR first, classify second). anpr.py adds confusable coercion
  (MHO2FX2660→MH02FX2660), state-code validation, Universal-Key vision fallback, and
  plate_status/confidence/source/reason persisted on incidents (migration 0007 applied to Neon).
- Mobile incident detail reworked to result-card layout (media+badge, plate card w/ copy,
  object/device location, captured-at). Webdash Department has incident modal with same layout.
- 147/147 pytest. Live verified on prod data: incident 668d75cc → MH02FX2660 (64%, rekognition).
- Local postgres/redis must be reinstalled after each fork (see PRD runbook).

## Prompt 10 (Part D) — Celery-free production (2026-06)
- app/scheduler.py (APScheduler, 5 jobs, Redis NX locks jobs:lock:*), face verify + SOP ingest
  → BackgroundTasks, pg_dump fallback to Python SQL dump (pg_dump was silently broken vs Neon
  PG17). Live-proven: backup R2 key, face score 100.0 in-process, lock dedupe (celery skipped).
- 152/152 pytest. RSS: API ~135MB steady; SOP embed spike 660MB → ~100MB after release_model().

## Prompt 11 — Optimistic submit + EyeLoader + logo assets (2026-06)
- Optimistic incident submit via outbox (oid param on success screen, live upload progress,
  results map for AI-card handoff); reports outbox chips Uploading…/Will retry/Waiting to send.
- EyeLoader replaces every ActivityIndicator (16 files); BlinkingLogo idle header anim;
  webdash CSS eye loader. Icon/adaptive/splash/favicon regenerated from user's white 1024 logo.
- Frontend testing agent iteration_12.json: ALL PASS — submit→success in 117ms, uploading→sent
  transition + AI card verified live (incident #835FEA22). No ActivityIndicator left (grep=0).
- NOT web-testable (verify on v1.0.2 build): app icon/splash, video capture, BLE.

## Prompt 12 — Real-logo EyeLoader + incident audio playback (2026-06)
- EyeLoader now composes the real logo layers (eye-base.png + eye-iris.png); iris ±12%W with
  250ms holds + full-logo blink. RN-WEB GOTCHA: Animated.Image ignores transform on web — wrap
  iris in Animated.View. Verified: translateX -5.9→+5.9→0, blink scaleY 0.947 (computed styles),
  webdash CSS twin frames left/mid/right.
- Voice notes playable by approvers end-to-end: voice_note_url in incident + dashboard payloads,
  .m4a→audio/mp4 MIME fix, mobile AudioPlayerCard (incident detail, progress+duration), webdash
  modal <audio>. Live Marathi note verified: incident 5b3ccaa2 (DO NOT DELETE), mobile 0:03/0:10,
  webdash duration 10.176s. iteration_13.json PASS.

## Prompt 13 — Dept switcher (CGM/MD) + Yema G prod insert (2026-06)
- Switcher chips on My Department for rank<=2; backend 403s cross-dept for rank>=3 (both list
  and submit — note manager submit threshold FIXED from >3 to >2). 158/158 pytest (6 new in
  test_dept_switcher.py, 2 rewritten in test_forms.py). pgvector must be built from source for
  the local test DB in fresh forks. Frontend E2 pass: iteration_14.json ALL PASS.
- Prod: Yema G emp_id 1212 (+919309491145, TIME_OFFICE Manager, GEN) — count 402→403; flagged
  + onboarding queues verified 200 via minted JWT; not whitelisted (real OTP path).

## Prompt 13 — Speed Pass #2 + Media Viewer + Brand Polish (2026-06)
- Cache-first profile startup, approvals SWR cache, skeletons, OTP hint, 2s AI polling.
- MediaCard + MediaViewerModal everywhere media renders (mobile + webdash modal). BrandFooter
  maroon #7A1F2B on tab-bar-less screens + webdash. 158/158 pytest, i18n 329 parity,
  E2 iteration_15 ALL PASS. Video viewer + pull-gesture = device-only verification.

## Prompt 17 (2026-06) — Parts B–F code complete, v1.0.8 candidate (DO NOT auto-deploy)
- Backend pytest: 183/183 green (tests/test_prompt17.py adds 10: direct-add, role guardrails, patch guardrails,
  role propagation w/o re-login, TO search access, escalate dept/employee incl. 403/422/409, escalation-targets,
  announcement scoping, push-mirror token recorder, face-enroll flow incl. reset path).
- Testing agent iteration_16: backend live E2E 17/17 passed; frontend flows verified (CGM tiles, announce composer,
  employees search/direct-add/edit). 2 minor frontend issues reported and FIXED after: employees search race
  (request-seq guard), announce back-nav on web (canGoBack fallback), phone +91 auto-prefix.
- Escalation verified E2E on web: manager 9000000101 escalated incident → status escalated, escalated_to set,
  timeline 'escalated' (manual), notifications delivered. Worker Alerts shows 📢 announcements + forwarded notices.
- KNOWN WEB-PREVIEW QUIRK (pre-existing, NOT a regression — verified identical on pre-P17 code): on the dev web
  bundle, tab screens' cached fetches can stall 15–30s behind Metro's connection pool, so Alerts may show the
  empty state for up to ~30s before rows appear. Data + badge are correct; native builds unaffected.
- Face enrollment + CaptureGuards are NATIVE-ONLY by design (web bypass). Push delivery requires a built APK;
  token registration is a safe no-op in Expo Go/web.

## Prompt 21 (2026-07) — Pre-launch triage + Time Office role mgmt
- Bug1 hardening verified live: boot line OTP CONFIG, fail-fast OTP_MODE_NOT_SET, demo default OFF,
  rate limit 5/10min + 45s cooldown (429 carries retry_after_seconds en/hi/mr), raw SMSGatewayHub logging.
- Bug4 backend fallback verified live (409→200). Time Office rails verified live 6/6 (grant Manager 200,
  edit Manager 200, grant CGM 403, edit CGM 403, demo assign-manager 403, worker patch 403).
- iteration_17 (frontend, web): ALL PASS — TO login, Manager chip, role grant+revert, HOD button visible,
  demo HOD press → 403 toast, no crash. EscalateModal submit modes code-reviewed (session limits), backend green.
- Pytest NOT runnable in this fork (no local PG/Redis); suites updated for new policy: test_prompt17,
  test_admin_misc, test_auth (rate limit), live_prompt17_api. Run on server/CI.

## HARDCORE QA CAMPAIGN (v1.0.10) — Phases 0/1/2 — 2026-07-26
Evidence via /tmp/camp_*.py against sandbox backend + live Neon (READ-ONLY for real rows; demo-only writes, 60-min auto-purge).
PHASE 0: 196/196 pytest pass in isolated env (local PG16+pgvector+Redis). 0 skipped/xfail.
  ISSUE #1 (FIXED, approved): conftest.py used setdefault(DATABASE_URL) → kept inherited PROD Neon URL, then drop_all() = prod wipe. Now FORCE test URLs + hard-abort unless _test/localhost/127.0.0.1. Proven: guard blocks a simulated Neon URL before any connect; 196/196 still pass. .dockerignore excludes backend/tests/ (only thing that prevented disaster).
PHASE 1 PASS: OTP send/resend/5-per-10min window(6th=429 retry_after trilingual)/JWT verify+refresh+expiry+tamper reject; demo-code 123456 REJECTED on PROD for real+demo numbers (M.2/M.5=401); unknown-number blocked 403 registration_closed (no SMS). Registration chain: reg-token upload 200, no_face 400, bad-magic-bytes 400. Punch matrix: inside=verified, dup=409, punch-out ok, outside=flagged(outside_geofence), gps-less=flagged(gps_missing), beacon MAC=verified. Incident submit 200 + AI classify (safety→PRODUCTION/high/0.9 via gemini-2.5-flash) + worker confirm-routing. Lifecycle: in_progress→resolve-without-photo=400 resolution_photo_required→resolve-with-photo 200. Escalation: person-mode 200 escalated_to set; dept-mode STORE fallback 200; CGM-own-dept fallback 200. Forms×13: all render; 7 submit clean, 6 require photo (by design); required-field enforced 13/13. Time Office matrix 7/7 (grant Manager 200, grant/edit/direct-add CGM 403, direct-add Manager 200, assign non-Manager/demo HOD 403). Announcements: own-dept 200, other-dept 403. Security: worker announce/grant-role/escalation-targets/resolve = 403; cross-tenant IDOR (demo→real incident)=404; escalate-nonexistent=404. AI: ANPR clear=exact(vision), blurry/no-plate=null fail-safe, confusable=Rekognition fallback; RAG no-SOP="could not find in uploaded SOP documents" (NO hallucination, EN+MR); Pulse/overview 200; missing-file=404 clean; voice-fill reachable. Webdash password-login: CGM 200, wrong-pass 401, worker 401.
PHASE 2 PASS: DB isolation ALL cross-tenant is_demo mismatch=0 (incidents/attendance/form_sub); orphans=0 (1 real emp "Eyam" NULL dept = expected pending_approval self-reg, by design). Scheduler: 6 jobs registered+firing; "skipped — already executed by another container" = Redis NX lock (jobs:lock:*) prevents double-run (PROVEN). Demo sweep cadence 15min / age threshold 60min (DEMO_MAX_AGE_MINUTES) — working. SMS otp_mode=demo(sandbox)/smsgatewayhub(prod), entity_id BLANK, template_has_{#var#}=True.
ISSUES: (2 week-1) shift-swap respond/decide TOCTOU race — concurrent double-accept=[200,200] → dup manager notif+audit; decide protected by uq_shift_assignment (no shift corruption, would 500 on concurrent approve). (week-1) NO idempotency key on incidents/forms → outbox retry after mid-upload drop = duplicate (punch guarded by per-day 409). (backlog) restore_latest.py DROP SCHEMA + seed scripts shipped in prod image (restore guarded by --yes). (backlog) upload magic-check validates header only (corrupt-body-valid-header stored). (minor) GET /admin/employees/{id} → 405 (no route).
COVERAGE GAPS (need Mumbai host / device / isolated load): R2 upload+backup object key; Rekognition-from-Mumbai-account confirm; scheduler firing on host; webdash UI + nightly PDF Devanagari; Bug-2 on-device camera; push delivery (needs build); Phase-3 500VU load (isolated env, scheduled).

## WEBDASH FULL UI PASS + SEARCH FIX (v1.0.10) — 2026-07-26
- FIX (last backend change before freeze): dashboard.py incidents-feed `q` search 500 —
  `Incident.category` is pg enum INCIDENT_CATEGORY; ILIKE needs `sa_cast(..., String)`.
  Verified sandbox+Neon: q=KL26J3344/vehicle/safe/SECURITY/no-q all 200. Commit 7e7c612.
- UI PASS (CGM via OTP + injected JWT, 1920x800): login, complaints feed (critical-first),
  plate search KL26J3344 → 1 row + detail modal (photo/plate/badges), overview KPIs+pulse+13 dept
  tiles, dept detail (SECURITY: trends chart, register, 13 open complaints), approvals (45 rows,
  per-manager cards), attendance register (empty-state OK; ~4s Neon latency on dept endpoint),
  reports (7 nightly EN PDFs + Ask Sahayak), admin (geofence 19/74.7/500m, 0 beacons, 6 no-phone,
  SOP empty), Marathi UI toggle fully Devanagari.
- NIGHTLY PDF DEVANAGARI: generated mr+hi+en locally from prod data (read-only, no R2/notify);
  fpdf2+uharfbuzz shaping renders conjuncts/matras correctly (अभियांत्रिकी, चिह्नित, घटनाएँ). PASS.
- BY DESIGN (not bugs): pulse + nightly-PDF language follows CGM language_pref (currently en),
  not the webdash toggle → EN-only reports list. Approvals shows "— (null)" card for Eyam
  (NULL-dept pending self-reg; disappears after cleanup). Feed rows without photo show gray box.
- HELD: scripts/cleanup_prelaunch.py awaiting explicit "RUN CLEANUP". Shift-swap TOCTOU +
  outbox idempotency deferred to post-launch (user choice b/b).

## FIELD FAILURE FIX-PACK (2026-07-27/28, pre-launch) — commits 7e7c612..e3111c4
- STAGE 1 diagnosis: (i) geofence was placeholder 19.0/74.7/500 → 35 km off; user pasted
  19.313483/74.709384/1200 (verified live). (ii) ZERO beacon payloads in all 4 field punches —
  root cause `neverForLocation:true` on ble-plx plugin (Android 12+ OS filters iBeacon frames),
  + LOW_POWER 3s scan window + fail-open permission skip. (iii) ladder: outside_geofence beat
  matched beacon. (iv) 0001/1212 face score NULL = ghost references (NoSuchKey on R2).
- A BEACON WINS (c0c08c9, DEPLOYED to EC2 by user): matched registered beacon → verified_plus
  regardless of GPS; flagging only when no beacon. 8-test matrix + live demo-punch proof.
- C2 (2a407ed): ble_zone added to incidents-feed + department serializers (webdash read it but
  backend never sent it); Department modal zone block. Live-verified 3 render points.
- Ghost-ref hardening (f80b1f4): NoSuchKey on reference at compare → clear stale key +
  re-bootstrap this punch (flagged reference_bootstrap) + audit. test_ghost_reference_rebootstraps.
- v1.0.11 (0a3ef32): neverForLocation removed; scanMode LOW_LATENCY, 10s early-exit scan;
  Nearby-devices perm in CaptureGuards (Allow/Open Settings, canAskAgain) + fail-closed trilingual
  abort in punch flow; incident camera behind same strict guards (C1). versionCode 10011.
- Local PG16+pgvector+Redis rebuilt in this pod; full suite 204 passed. KNOWN FLAKE (pre-existing):
  test_demo_isolation::test_nightly_report_excludes_demo_rows fails when UTC date != IST date
  (18:30-00:00 UTC) — IST 'today' vs created_at::date(UTC) mismatch in the TEST query.
- STAGE3_v1.0.11_TEST_PLAN.md: evidence tables + 20-min field protocol + ship matrix.
- Beacons registered earlier (6 iBeacon rows, shared registry, no is_demo column).
- NOTE: B/C1 are native-only — NOT verifiable in Expo Go/web; device APK required.

## Launch-eve follow-ups (2026-07-28 ~02:00 IST) — commit f5790b9
- cleanup_prelaunch --execute crash FIXED: implicit autobegin txn from report reads made
  session.begin() raise InvalidRequestError; session.rollback() before begin. Crash reproduced
  + clean EXECUTE verified on local PG (10/10 preservation checks); Neon dry-run green.
- webdash Attendance: "All departments (flagged)" option (factory-wide pending list via
  /attendance/flagged?date=, dept column, approve/reject) + fixed date-picker/lang-switch
  overlap. Verified with real row 0001 (approve+reject rendered, overlap check False).
- Mobile Approvals->Attendance has NO Reject button (only att-approve-*, actAttendance only
  calls approveAttendance; backend reject endpoint exists) — classified NEXT APP BUILD (v1.0.12
  candidate); webdash register is the workaround.
- User: rejected 3 of 4 flagged rows (0001 pending), skipping ref-clear curls (ghost-ref
  hardening self-heals 0001/1212), building v1.0.11 APK+AAB via Publish.

## LAUNCH-DAY EMERGENCY: v1.0.13 dead API base + DNS outage (2026-07-28) — commit e908ca8
- P0-A DNS: api.hogoplus.in was NXDOMAIN on Google+Cloudflare (hogoplus.in zone reset to Hostinger
  parking NS during website/privacy.html setup; SOA bumped same day). User re-added A record ->
  13.204.160.31 TTL 300; propagation verified from this pod; prod health 200.
- P0-B v1.0.13: pipeline env injection can bake EMPTY EXPO_PUBLIC_API_URL -> API_BASE="/api"
  relative -> instant RN network error (login + outbox share client). ALSO proven: metro
  transform-cache poisoning — export with empty env then correct env still baked "" (cache
  re-served). FIX v1.0.14 (10014): client.ts release builds PIN https://api.hogoplus.in
  (__DEV__ keeps env for sandbox). Bundle greps: empty-env, poisoned-cache and clean exports
  all pin prod URL, zero preview/localhost bases. hermesc cannot run on this aarch64 pod —
  use --no-bytecode for local artifact exports.
- Artifact smoke on prod: send-otp +919000000500 -> 200 demo_account @ 2026-07-28T16:51:34Z
  (IST 22:21:34); unknown +919888777666 -> 403 registration_closed trilingual @ 16:51:58Z.
- Regression: backend suite 205/205 PASSED (PG16+pgvector+redis reinstalled — pod had reset).
  Frontend sweep (testing_agent iteration_18): 7/8 PASS, offline-outbox partial (headless
  can't capture photo; outbox path code-verified). Device-only rows -> field protocol.
- frontend/.env temporarily pointed at sandbox for the sweep, RESTORED to api.hogoplus.in.

## v1.0.15 — neverForLocation merge-time fix + app batch (2026-06 fork)
- ROOT CAUSE (artifact autopsy): ble-plx LIBRARY manifest re-injects BLUETOOTH_SCAN
  neverForLocation via Gradle manifest merger AFTER prebuild (v1.0.14 artifact had
  usesPermissionFlags=0x00010000 despite clean app.json). FIX: config plugin
  plugins/withBleScanNoNeverForLocation.js stamps tools:remove="android:usesPermissionFlags"
  (merge-time authority, re-applied by every prebuild). Prebuild-verified in /tmp copy.
- Batch: Approvals attendance Reject button, no-beacon reason i18n ×3, capture zone chip
  (native only) + enriched beacon-registry labels (backend deployable now).
- pytest 211/211; tsc + eslint clean; testing_agent iteration_19 ALL PASS.
- beacon_first_mode=False confirmed post-test; frontend/.env restored to api.hogoplus.in.

## v1.0.16 — TRUE root cause (ble-plx manufacturerData clobbering) + field instrumentation
- v1.0.15 artifact was CLEAN (user autopsy) yet detection failed. Real bug: ble-plx Android
  AdvertisementData.parseManufacturerData OVERWRITES its single manufacturerData field for EVERY
  0xFF AD structure; vendor beacons put their config frame in the SCAN RESPONSE which Android
  merges AFTER the Apple iBeacon frame -> vendor frame clobbers 4C 00 02 15 before JS sees it.
- Fix: src/ble/ibeaconParse.ts extractIBeacons() signature-scans rawScanRecord (full merged
  record) at ANY offset, all frames; ibKey Number-coerces major/minor. Unit-proven:
  frontend/scripts/test-ibeacon-parse.js (16/16, incl. old-parser failure repro).
- User hypotheses (a) case (b) type (c) uuid-format ELIMINATED by the same test.
- requestBlePermissions now also requires/requests ACCESS_FINE_LOCATION on Android 12+
  (mandatory for scan results once neverForLocation removed; catches approximate-only grants).
- Instrumentation: hidden BLE Diagnostics screen (long-press Profile avatar) -> live scan dump
  with per-candidate verdicts; POST /api/attendance/ble-diag stores report as audit ble.diag;
  GET /api/admin/ble-diag (CGM/MD) reads back. pytest 214/214, tsc+eslint clean, web smoke OK.
- frontend/.env restored to api.hogoplus.in after smoke.

## v1.0.17 SPEED PACK + incident zone session + Play in-app updates (iter 20 PASS)
- Punch flow rewritten for parallelism (pre-warmed shared ZoneSession, GPS|upload|zone(<=5s)|geocode
  in parallel, late attach via POST /attendance/{id}/attach-beacon). Incident uses the SAME session.
- Registry cached locally (10-min TTL, bg refresh, stale-if-offline). Punch timing breakdown stored
  and visible in BLE Diagnostics + included in diag report.
- Play In-App Updates via sp-react-native-in-app-updates + UpdateGate (flexible default,
  IMMEDIATE when app_versions.force_update=true — migration 0012). UpdateGate.web.tsx stub added by
  testing agent (P0: metro static-resolves native-only require on web) — KEEP.
- PDF nightly: critical incidents now show beacon zone.
- pytest 218/218; tsc+eslint clean; ibeacon unit tests 16/16; iter20 frontend E2E all pass.
- .env restored to api.hogoplus.in. Prod app-version row still 1.0.7 — bump via PUT /admin/app-version
  when 1.0.18 ships to trigger the in-app update flow.

## v1.0.18 — keyboard-controller migration + prod phone update + self-reg validation (2026-06 fork)
- Emp 0061 phone updated LIVE Neon → +917020892694 (dup-check none, dry auth-check ok, CSV synced;
  seed.py insert-only so no re-seed drift possible).
- Keyboard: react-native-keyboard-controller@1.18.5 everywhere (see PRD). NATIVE-ONLY — web is
  passthrough; APK field test required for actual avoidance. Web regression sweep (agent iter21 +
  main-agent JWT-injection Playwright): sahayak/announce/employees/emp-form/swap/incident/escalate/
  form-engine inputs ALL accept text, zero regressions. eslint clean.
- Testing-agent harness note: hidden OTP input is flaky under Playwright locator.fill (real users
  unaffected). Workaround that WORKS: fetch JWT via /api/auth/verify-otp, inject localStorage keys
  hogo.access/hogo.refresh (JSON.stringify'd), hogo.profile (double-stringified), hogo.langPicked/
  permsPrimed/permsReprimed/faceEnrollAsked = "true", then navigate.
- Self-registration API E2E ALL PASS (scripts/selfreg_e2e.py); Rekognition face gate confirmed live;
  test registrant rows cleaned from prod DB (+919999900011/12 → NONE).
- Perf report: /app/docs/PERF_PROFILE_v1.0.17.md (fixes deferred to v1.0.19 per user).
- app.json 1.0.18/10018; frontend/.env restored to api.hogoplus.in. Prod app_versions row still
  1.0.7 — bump via PUT /admin/app-version after 1.0.18 goes live to trigger in-app update.

## WAVE 1 dept upgrade (v1.0.19) — 2026-06 fork
- Backend: migration 0013 (home_configs, vehicle_logs, 3 settings flags default OFF) applied to
  prod Neon; routers home.py + vehicles.py; notify batching/quiet-hours/retry; vehicle_overstay
  sweep in scheduler (hourly :12). 231/231 pytest. conftest adds sec_mgr 0004 / w_sec 0016.
- IMPORTANT GOTCHA: mobile api client base = EXPO_PUBLIC_API_URL (NOT EXPO_PUBLIC_BACKEND_URL).
  For preview testing set EXPO_PUBLIC_API_URL to the preview URL + restart expo; restore to
  https://api.hogoplus.in before builds. Metro also caches inlined env — bust with
  mv /app/frontend/.metro-cache if changes don't appear.
- Vehicle log day filters are IST-based on both app and webdash (toLocaleDateString en-CA
  Asia/Kolkata) — matches backend IST day windows.
- test_demo_isolation nightly-report test was flaky between 18:30-24:00 UTC (IST date rollover);
  fixed by using UTC date consistent with _report_data's func.date(created_at).
- Testing agent iteration_22: ALL PASS (17/17 API, all mobile flows, webdash incl. XLSX).
  live_v1019_api.py added under backend/tests (live spot-check script).
- Flags to flip for real users when user says go: PATCH /api/admin/settings
  {home_config_enabled, vehicle_log_enabled, notif_batching_enabled}.

## v1.0.21 P0 — voice-first + TTS (iteration_23 ALL PASS)
- New: POST /ai/voice-describe (Whisper→LLM desc, cap 20/day/user), POST /ai/tts (sha256 server
  cache + on-device mp3 cache, cap 30/day/user, cached hits free), server-side desc fill for
  offline voice incidents, SpeakerButton on alerts/AI cards/pending, voice-first capture layout.
- pytest 249 passed (+14 tests/test_voice_tts.py); live smoke scripts/live_voice_smoke.py;
  testing agent iteration_23 all pass incl. fake-camera capture flow.
- Harness note: page.type(delay=100) on otp-input worked this time; JWT-injection fallback still valid.
- frontend/.env EXPO_PUBLIC_API_URL → preview URL (restore api.hogoplus.in before builds).

## v1.0.22 — nudge + swap FOR UPDATE + outbox idempotency (2026-07-30 fork)
- Sweep two-stage (remind 15min / flag 2h no_punch_out, never auto-punch), covers overnight
  B rows dated yesterday; flagged queue/regularize/approve/reject accept no_punch_out; punch-out
  self-clears. client_uuid dedup on incidents+forms (migration 0016). with_for_update on swap
  respond/decide/cancel — real concurrency tests prove single apply.
- pytest 284 passed. testing_agent: backend 5/5 + frontend 3/3 PASS, 0 bugs. Whitelist gotcha:
  use demo TO D113 (+919000000113) with demo worker D001 — real TO phone not in sandbox whitelist.
- BACKUP_UPLOAD_ENABLED=0 in sandbox backend/.env is a DELIBERATE DR guard (sandbox dumps were
  overwriting prod R2 backup keys) — never remove it; prod defaults ON.
- frontend/.env restored to api.hogoplus.in; app.json 1.0.22/10022.

## v1.0.22b — MD dashboard vehicle bug + app-version gap (2026-07-31)
- ROOT CAUSE: prod settings.vehicle_log_enabled=false → 403 feature_disabled on all
  /vehicles/* for every real user; webdash stuck on Loading. Evidence: prod snapshot DB
  value + browser console 403 + backend access log; NOT RDS/PG18 related.
- Fixed: Vehicles.tsx friendly disabled panel + one-click enable (top mgmt); Admin card for
  app-version (validated: semver pattern, https-only apk_url, placeholders rejected) +
  feature-flag toggles; UpdateGate force-update block screen (native build required to test).
- restore_latest.py: strips PG18 pg_dump artifacts (\restrict, SET transaction_timeout) so
  RDS full dumps restore onto PG16 sandbox.
- 287 pytest passed; webdash rebuilt; E2E browser-verified as real CGM with screenshots.

## v1.0.22c — range export + flag truth card (2026-07-31)
- Vehicles export: From→To inputs default to current month; register day view unchanged;
  ranged xlsx covered by test_export_xlsx_date_range.
- Admin Feature-flags card = one-screen truth (4 flags with ON/OFF badges + dup rules).
  Prod audit: home_config_enabled + notif_batching_enabled still DARK; beacon_first OFF is
  intentional policy. Runbook now ends with flag-flip + app-version as explicit final lines.
- 287 pytest passed; webdash rebuilt; browser-verified as real CGM.

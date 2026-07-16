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

# DEPLOY ORDER — v1.0.25 (Live Presence Phase 1 complete + Back-button redo + App-Store blockers)

## What ships
1. **Live Worker Presence Phase 1 — COMPLETE** (backend was v1.0.25-pre, now + webdash + mobile)
   - Webdash `/api/dash/presence`: KPI strip, 29-zone board (busiest first, hide-empty, search),
     OSM/Leaflet map (geofence 1200 m @ 19.313483,74.709384, zone pins with counts, green/red/grey
     worker dots, clustering), worker list (search / dept / zone / status filters, outside-first),
     15 s auto-refresh + "updated Xs ago", EN/HI/MR, works at 360 px.
   - Mobile: Marathi-first consent (`/presence-consent`, version 1.0, stored server-side),
     foreground-ONLY tracker (`src/presence/tracker.ts` + TaskManager task): BLE zone first,
     GPS fallback, change-based upload + 5-min heartbeat, offline queue (idempotent
     client_ping_id replay), starts at punch-in, stops at punch-out AND at shift end + 30 min
     (`stop_after` from /presence/my-status), server 403/409 also stops it. Home status chip
     (green/amber/blue), GPS-off Marathi nudge, OEM battery help (`/battery-help`).
2. **Back button** — shared ScreenHeader on every non-root screen (all roles), Android hardware
   back: sub-screen→pop (orphan deep-link→home), non-home tab→home, home→double-press-to-exit.
   Regression guard: `cd frontend && yarn check:headers` (fails CI if a screen lacks the header).
   Full table: `docs/BACK_BUTTON_ROUTE_TABLE.md`.
3. **App-Store blockers**
   - In-app deletion: Profile → Delete my account → MR/HI/EN warning → OTP re-verify →
     deletes name/phone/selfies/face-reference/push-token/presence trail/consents/password,
     anonymises legal rows ("Deleted user #emp_id", attendance kept w/ selfie_key='deleted'),
     is_active=false kills all tokens, audited (`account.deleted`). Demo/reviewer accounts → 409.
   - Privacy policy hosted at **GET /api/legal/privacy** (public, EN + MR, covers shift-only live
     location, 30-day purge, viewers, consent, deletion, contact) — linked from Profile and
     the registration name screen. Canonical file: `backend/legal/privacy.html`.

## EC2 deploy order
```bash
git pull                              # pull main FIRST (standing rule)
docker compose build api              # webdash now built with npm ci (package-lock.json committed)
docker compose up -d api
docker compose exec api alembic upgrade head   # applies 0018_live_presence (if not yet applied)
```
No new migration beyond **0018_live_presence** (already created last session). No seed script.

## Flags / settings (all default OFF — nothing changes for users until flipped)
- `settings.live_presence_enabled` (DB) — global kill-switch, default FALSE.
- `settings.presence_pilot_emp_ids` (DB, comma-separated emp_ids) — per-worker pilot list.
  BOTH must be on for a worker to be tracked; consent + punched-in are also required.
- Flip via webdash: PUT /api/presence/settings (CGM/MD) or the presence page "Enable" button.
- No new .env variables. (Sandbox-only: DEMO_OTP_WHITELIST gained +917111222333 for tests.)

## Mobile build (APK/IPA 1.0.25 / versionCode 10025 — via Emergent Publish)
- app.json: expo-location plugin now `isAndroidForegroundServiceEnabled: true`,
  `isAndroidBackgroundLocationEnabled: false`, `isIosBackgroundLocationEnabled: false`.
- MANIFEST AUTOPSY (expo prebuild, android, 2026-09-18):
  - `FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_LOCATION` PRESENT ✓
  - `ACCESS_BACKGROUND_LOCATION` ABSENT ✓
  - `BLUETOOTH_SCAN` carries `tools:remove="android:usesPermissionFlags"` (neverForLocation stripped) ✓
  - API pinned to https://api.hogoplus.in in release builds (src/api/client.ts guard) ✓
  - NO new iOS background modes / Info.plist strings ✓
- iOS honesty note: with no background mode, iOS tracks only while the app is open.
- Foreground-service tracking + BLE scanning need a REAL BUILD — Expo Go/web preview only
  exercises the consent + web-interval fallback.

## Verification (all done in sandbox, 2026-09-18)
- pytest: **315 passed, 2 skipped** (new: tests/test_account_deletion.py ×5; test_presence.py 9/9)
- testing_agent iteration_27: backend 4/4, webdash + mobile web flows PASS, 0 product bugs
- E2E: consent → live GPS ping → worker_presence row (inside_geofence=true) → dashboard
- E2E: DEL01 account deleted via UI → row anonymised, signed out, audit written
- Webdash clean build proof: `rm -rf node_modules && npm ci && npm run build` ✓ (EC2-safe)

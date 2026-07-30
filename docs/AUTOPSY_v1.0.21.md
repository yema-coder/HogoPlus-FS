# AUTOPSY — v1.0.21 "six-feature batch" (P0 voice/TTS + P1 attendance/entry/dedup)
One build. Backend deploys FIRST, phone installs SECOND. This document is the evidence.

## 0. Verdict table

| # | Feature | Backend | Mobile | Tests | Live evidence |
|---|---------|---------|--------|-------|---------------|
| 1 | Voice-first incident reporting (Whisper STT) | `POST /api/ai/voice-describe` | capture.tsx speak-first layout | test_voice_tts.py (14) | Real Marathi audio + 10 dB machine noise → correct transcript → Gemini/GPT description |
| 2 | Read-aloud everywhere (TTS) | `POST /api/ai/tts` + server cache | SpeakerButton on alerts/incident detail/success/pending | test_voice_tts.py | Real 4.2 s mp3, `cached=true` on 2nd call |
| 3 | My Month attendance | `GET /api/attendance/mine`, `GET /api/attendance/month-summary` | attendance/history.tsx "📅 My Month" card | test_p1_batch.py (501 lines) | testing_agent iteration_24 ALL PASS |
| 4 | Attendance regularization | `POST /api/attendance/{id}/regularize` + mine/queue/decide | "This is wrong" on flagged rows; manager dispute queue in Approvals | test_p1_batch.py | iteration_24 ALL PASS |
| 5 | Same-as-last quick entry | `GET /api/vehicles/last-mine`, `GET /api/forms/{id}/last-mine` | vehicle/new.tsx "⏮ Same as last entry" chip; FormRenderer "Fill like last time" | test_p1_batch.py | iteration_24 ALL PASS |
| 6 | Duplicate incident detection | clustering in tasks.py on create; `POST /api/incidents/{id}/unlink-duplicate` | dup banner + "View first report" + "Not same — unlink" in incident detail | test_p1_batch.py | iteration_24 ALL PASS |

Suite: **276 backend tests passing** against live local PG+Redis. tsc clean, eslint clean.
testing_agent: iteration_23 (P0) ALL PASS, iteration_24 (P1) ALL PASS, 0 bugs.

## 1. THE API URL — confirmed in writing (check this first)

**Two independent protections; either alone is sufficient:**

1. `frontend/.env` → `EXPO_PUBLIC_API_URL=https://api.hogoplus.in` (restored from the
   sandbox preview value on 2026-07-30, before this build; `EXPO_PUBLIC_BACKEND_URL`
   likewise, though nothing in app code reads it).
2. **Release-build pin** in `frontend/src/api/client.ts` (since the v1.0.13 field
   failure): in any non-`__DEV__` bundle the base is hard-pinned:
   ```ts
   const PROD_API_URL = "https://api.hogoplus.in";
   ...
   resolvedBase = __DEV__ ? (BASE || PROD_API_URL) : PROD_API_URL;
   ```
   Even if the build pipeline's env injection replaces or empties
   `EXPO_PUBLIC_API_URL`, the release bundle still talks to api.hogoplus.in.

**Artifact grep — run on the APK before any phone gets it:**
```bash
# 1) prod host is baked in (expect a number >= 1)
unzip -p HogoPlus.apk assets/index.android.bundle | strings | grep -c "api.hogoplus.in"

# 2) NO sandbox/preview/localhost leaked (expect ZERO lines)
unzip -p HogoPlus.apk assets/index.android.bundle | strings \
  | grep -E "preview\.emergentagent|localhost:8001|10\.0\.2\.2"

# 3) version identity (expect versionName 1.0.21)
aapt2 dump badging HogoPlus.apk | grep -E "versionName|versionCode"

# 4) BLE permission regression check (expect NO usesPermissionFlags line under BLUETOOTH_SCAN)
aapt2 dump xmltree HogoPlus.apk --file AndroidManifest.xml | grep -A1 BLUETOOTH_SCAN
```
app.json: `version 1.0.21`, `versionCode 10021` (pipeline may assign its own higher versionCode — fine, just record it).

## 2. DEPLOY ORDER — what must be live on EC2 BEFORE the APK reaches a phone

Compatibility: **old app (1.0.20) + new backend = fully safe** (everything is additive).
**New app (1.0.21) + old backend = the six features 404.** Hence: backend first, phone second.

```bash
# ── on EC2 ────────────────────────────────────────────────────────────────
cd /opt/hogoplus

# 1) pull the v1.0.21 code (backend + everything)
git pull

# 2) the dedicated OpenAI key — BEFORE the rebuild so containers boot with it
#    (production AI: Whisper STT, TTS, incident classify, voice-fill, Sahayak all bill here)
echo 'OPENAI_API_KEY=sk-...' >> /opt/hogoplus/.env
# optional, default is gpt-4o-mini:
# echo 'OPENAI_MODEL=gpt-4o-mini' >> /opt/hogoplus/.env

# 3) rebuild + restart the stack (api, worker, beat share the image)
docker compose up -d --build

# 4) apply migration 0015 (ADDITIVE ONLY — no destructive ops):
#    incidents.duplicate_of, settings.dup_window_minutes/dup_same_zone/dup_same_category,
#    new table attendance_regularizations (+ partial unique idx: ONE open request per punch)
docker compose exec api alembic upgrade head
docker compose exec api alembic current        # → 0015
```
(`api` = your compose service name; if yours is `backend`/`hogoplus-backend`, substitute as in past deploys.)

**Boot-log gates (do not install the APK until both pass):**
```bash
docker compose logs api | grep "AI CONFIG" | tail -1
# MUST show: AI CONFIG: llm=openai/gpt-4o-mini stt=whisper-1 tts=tts-1 key_source=openai-dedicated
# If it says key_source=emergent-universal-FALLBACK → the key didn't load. STOP, fix .env, restart.

docker compose logs api | grep "Uploaded DB backup" | tail -1
# MUST be < 4 h old (backup job alive on the new image)
```

**Route smoke (proves the new endpoints are live; 401 = correct, they exist and demand auth):**
```bash
for p in ai/voice-describe ai/tts attendance/mine attendance/month-summary \
         attendance/regularizations vehicles/last-mine; do
  printf "%-32s %s\n" "$p" "$(curl -s -o /dev/null -w '%{http_code}' -X GET https://api.hogoplus.in/api/$p)"
done
# expect 401 (or 405 for the POST-only ai/* two) — anything 404 means old code is still running
```

**Explicitly NOT needed for this deploy:**
- No webdash rebuild (zero webdash changes since v1.0.20).
- No feature-flag flips. Duplicate rules ship as settings-table columns with server
  defaults (window 30 min, same zone, same category — tunable later without deploy).
  Voice caps are env-tunable with safe defaults: `VOICE_DESCRIBE_DAILY_CAP=20`,
  `TTS_DAILY_CAP=30` per user per day (server cache hits bypass the TTS cap).
- No Redis/infra change (caps + TTS cache use the existing Redis).

**AFTER field verification passes (not before):**
```bash
# flips the in-app update banner for the 1.0.20 fleet
curl -X PUT https://api.hogoplus.in/api/admin/app-version -H "Authorization: Bearer <admin>" \
  -H 'Content-Type: application/json' -d '{"version":"1.0.21", ...}'
```

## 3. BACKUP DRILL — the numbers (re-run 2026-07-30, timed)

**What was restored:** `backups/2026-07-31/0030.sql.gz` — 106,954 bytes gz, uploaded to R2
at 00:30 IST (19:00:19 UTC 2026-07-30), **2.3 h old** at drill time. Retention on the
bucket: 22 objects (48 h of 4-hourly + 14 dailies), sizes growing smoothly 93 KB → 107 KB
over the week — consistent with one live production DB.

**Restore into scratch db `hogoplus_drill`: 2.7 seconds wall clock** — download from R2 +
drop/recreate DB + `CREATE EXTENSION vector` + `alembic upgrade head` (0001→0015) + full
data apply. Bonus proof: **migration 0015 applied cleanly onto a real production snapshot**
during the restore — the exact upgrade your EC2 will run.

**Row counts after restore (production as of 2026-07-31 00:30 IST):**

| table | rows |
|---|---|
| employees | 447 |
| audit_events | 493 |
| notifications | 40 |
| attendance | 18 |
| incidents | 17 |
| form_submissions | 14 |
| vehicle_logs | 7 |
| public tables | 24 · alembic head `0015` |

**Spot check (integrity, not just counts):** newest employee in the restored DB is
`3003201 — Somnath Vasant Thorat`, `pending_approval`, registered **2026-07-30** — a real
field registration from the day before the backup. The scratch DB was dropped after
recording these numbers.

**Was the dump from RDS, not Neon?** Evidence chain:
1. Code: `app/tasks.py:run_backup_sync` dumps whatever `DATABASE_URL` the prod process
   runs with. There is zero Neon reference anywhere in code.
2. Neon has been READ-ONLY since your RDS migration — if prod still pointed at Neon,
   every write (punches, registrations) would 500. Somnath registered 2026-07-30 and is
   in the dump → prod is writing → prod is on RDS → **the dump is RDS data**.
3. Authoritative 30-second check on EC2 (Gate 1 in the field protocol):
   `grep '^DATABASE_URL' /opt/hogoplus/.env` → must be `*.rds.amazonaws.com`.

**⚠ NEW FINDING + FIX (found during this drill): sandbox↔prod backup key collision.**
The sandbox runs the same 4-hourly cron with the same R2 bucket, and keys are
`backups/YYYY-MM-DD/HHMM.sql.gz` — identical minute → **whoever uploads last overwrites
the other**. Sandbox celery logs prove it happened: sandbox uploaded
`backups/2026-07-15/2030.sql.gz` and `backups/2026-07-16/0030.sql.gz` (both since aged out
of retention). Today's `2026-07-31/0030` is clean (sandbox worker was down at 19:00 UTC and
only started 19:54). **Fix shipped in this deploy:** `BACKUP_UPLOAD_ENABLED` guard in
`run_backup_sync` — sandbox `.env` sets `0` (verified: task now returns
`{'skipped': True, 'reason': 'backup upload disabled'}`), production leaves it unset
(default ON, zero behavior change). To audit any past key: `docker compose logs api | grep
"Uploaded DB backup"` on EC2 is the ground truth of what PROD uploaded and when; any R2
object whose LastModified doesn't match a prod log line was a sandbox overwrite.

## 4. Per-feature autopsy — how each works, limits, failure modes

### 4.1 Voice-first reporting (P0)
- Hold-to-talk on incident capture → m4a upload → `POST /api/ai/voice-describe` →
  Whisper (`whisper-1`) STT → LLM writes a 1–3 sentence description **in the speaker's
  language** → fills the description field with an "AI" chip (manual edit clears it).
- **Failure modes handled:** LLM down → raw transcript used (never a dead end). Offline /
  request fails → voice note still queues with the report via the outbox; the worker sees
  "Voice saved — it will be written after sending"; the backend classify task fills the
  description from the transcript on arrival (typed text is never overwritten). Nothing
  heard → "Could not hear anything. Speak again or type."
- **Caps:** 20/user/day (Redis counter, trilingual 429). Recording capped at 60 s.
- **Limit:** Marathi orthographic variants (पम्प/पंप) mean transcripts are semantically
  right but not letter-perfect — hence the "Did we hear you right?" check hint.

### 4.2 Read-aloud TTS (P0)
- `POST /api/ai/tts` (text ≤ 600 chars) → OpenAI `tts-1`/alloy → mp3 in R2. Server-side
  Redis cache keyed sha256(text), TTL 30 d refreshed — the same sentence is **never
  synthesized twice** (cached hits bypass the 30/day cap). Client caches played mp3s on
  device (200-entry trim) → anything played once **replays offline**.
- Speaker buttons: every alert row, incident AI assessment (Marathi for mr/hi users),
  incident success screen, registration pending screen.
- **Limit:** audio never played before cannot play offline ("No internet — this audio is
  not saved yet").

### 4.3 My Month (P1)
- `GET /api/attendance/mine` + `month-summary`: IST day windows, C-shift previous-day
  attribution, 15-min grace lateness — the same rules the Time Office numbers use.
  Card shows days present, late days, last-month comparison.

### 4.4 Attendance regularization (P1)
- Flagged/wrong punch rows grow a "This is wrong" button → optional text AND/OR voice
  note → `POST /api/attendance/{id}/regularize`. **DB-enforced: one open request per
  punch** (partial unique index — no spam). Manager sees a dispute queue in Approvals
  ("Worker says" + voice playback) → approve/reject with note → worker sees "Under
  review / Corrected ✓ / Not accepted" on the row + notification.

### 4.5 Same-as-last (P1)
- Vehicle: "⏮ Same as last entry · X min ago" chip fills the previous plate/purpose/
  driver ("Same vehicle? {plate}" confirm). Forms: "Fill like last time" copies the
  user's own previous submission values ("Copied — check and submit"); per-field ghost
  values. Server-side (`last-mine`) so it works across devices/reinstalls.

### 4.6 Duplicate incident detection (P1)
- On creation, backend clusters: same zone + same category within 30 min (all three rules
  tunable in the settings table, no deploy) → `duplicate_of` set on the newer report.
  **Display-only by design:** submission is never blocked, escalation still runs on the
  original. Manager sees "Grouped with an earlier report", "View first report", and
  "Not same — unlink" (`unlink-duplicate`) when the heuristic is wrong.

## 5. Honest gaps / not verified
1. **`key_source=openai-dedicated` never live-tested** — no OpenAI key exists in the
   sandbox (by design). Gate 1 of the field protocol is the verification.
2. Voice recording quality on the cheapest fleet phones is protocol step, not lab-testable.
3. Duplicate rules are heuristics; the unlink button is the safety valve.
4. Keyboard follow-ups (P2) ride this build — spot-check is folded into the protocol.
5. Prod `app_versions` row: bump to 1.0.21 only AFTER the protocol passes.

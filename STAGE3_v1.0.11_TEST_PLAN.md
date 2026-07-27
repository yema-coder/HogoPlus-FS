# STAGE 3 — v1.0.11 HARDCORE TEST PLAN & EVIDENCE (2026-07-28, pre-launch)

Scope: field failure fix-pack — A (beacon wins, backend, DEPLOYED), B (beacon hearing,
APK), C1 (incident hard gate, APK), C2 (incident zone tag, backend+webdash deploy +
already-working app side), ghost-reference hardening (backend).

Legend: **PASS(proven)** = evidence produced in this environment ·
**DEVICE (v1.0.11)** = native-only, verify on the APK with the field protocol below.
Expo Go / web preview CANNOT exercise BLE scanning, Android runtime permissions or
manifest changes — claims are made only where proof exists.

## 1) Ladder matrix — (beacon, GPS) × reference states

| # | Case | Expected | Result | Evidence |
|---|------|----------|--------|----------|
| 1 | beacon + inside | verified_plus, zone stored | **PASS(proven)** | live demo punch D001/D006 + pytest `test_beacon_inside_verified_plus` |
| 2 | beacon + OUTSIDE geofence | **verified_plus** (THE FIX), flag None, gps_verified false | **PASS(proven)** | live D007 (`level=verified_plus`, zone=Main Gate, 34.8 km out) + pytest `test_beacon_outside_geofence_verified_plus` |
| 3 | beacon + GPS missing | verified_plus | **PASS(proven)** | live D002 + pytest `test_beacon_gps_missing_verified_plus` |
| 4 | no beacon + inside | verified | **PASS(proven)** | live D003 + pytest `test_no_beacon_inside_verified` |
| 5 | no beacon + outside | flagged `outside_geofence(<m>)` | **PASS(proven)** | live D009 (`outside_geofence(34871m)`) + pytest |
| 6 | no beacon + GPS missing | flagged `gps_missing` | **PASS(proven)** | pytest `test_no_beacon_gps_missing_flagged` |
| 7 | UNREGISTERED beacon + outside | flagged (beacon must be in registry to win) | **PASS(proven)** | live D008 + pytest `test_unregistered_beacon_outside_still_flagged` |
| 8 | MAC-mode beacon + outside | verified_plus (dual-mode parity) | **PASS(proven)** | pytest `test_beacon_mac_mode_outside_verified_plus` |
| R1 | first punch, no reference | face task overwrites → flagged `reference_bootstrap`, selfie becomes reference, TO queue | **PASS(proven)** | pytest `test_missing_reference_bootstraps` (+ observed live 27 Jul on 300319/0052) |
| R2 | reference exists, score ≥90 | face_verified true, level unchanged | **PASS(proven)** | pytest `test_score_90_plus_verifies` |
| R3 | reference exists, score <80 | flagged `face_mismatch` + TO notify | **PASS(proven)** | pytest `test_score_below_80_flags_and_notifies` |
| R4 | reference KEY set but OBJECT missing (ghost) | clear stale key → re-bootstrap from this punch → flagged `reference_bootstrap` + audit `reference_selfie_rebootstrap` | **PASS(proven)** | NEW pytest `test_ghost_reference_rebootstraps` |
| — | Full backend suite | all green | **PASS(proven)** | **204 passed**, 1 pre-existing UTC/IST time-window flake in `test_demo_isolation` (unrelated, documented) |

## 2) Incident flow

| Case | Expected | Result | Evidence |
|------|----------|--------|----------|
| With beacon in range | zone attached; shown on mobile card, webdash feed, feed modal, dept modal | **PASS(proven, backend+webdash)** | live demo incident 6acbae77 → `ble_zone=Godown Row A`; screenshots: feed row 📍, detail modal "Beacon zone", dept modal "📡 BEACON ZONE". Mobile card rendering pre-existing (`incident/[id].tsx:239`). Real-device hearing → **DEVICE (v1.0.11)** |
| Without beacon | proceeds exactly as before, no zone, zero new blocking | **PASS(proven)** | every pre-existing incident + pytest incident zone-context tests |
| BT off → camera blocked | strict guard, no Continue-anyway, trilingual | **DEVICE (v1.0.11)** — code: `capture.tsx` `<CaptureGuards camera location gps bluetooth strict>` |
| Location off → blocked | same | **DEVICE (v1.0.11)** |
| Airplane-mode outbox | punch/incident queue offline, auto-upload on reconnect | **DEVICE (v1.0.11)** — outbox code untouched this pack |

## 3) Permission paths

| Case | Expected | Result |
|------|----------|--------|
| Android 12+ first ask | guard shows "Nearby devices permission" row → Allow → native prompt | **DEVICE (v1.0.11)** |
| Android 12+ deny | guard blocks (strict), row shows Allow again | **DEVICE (v1.0.11)** |
| Android 12+ "Don't ask again" | row switches to **Open Settings** (`canAskAgain` respected via NEVER_ASK_AGAIN) | **DEVICE (v1.0.11)** |
| Deny then reach punch anyway | mid-flow second gate: trilingual toast `att.blePermRequired`, punch CANCELLED (fail closed) | **DEVICE (v1.0.11)** — `punch.tsx` |
| Android ≤11 fallback | no Nearby prompt; FINE_LOCATION (already granted in guard) covers scanning | **DEVICE** — `Platform.Version < 31 → granted` |
| iOS | Nearby perm N/A; iBeacon raw frames filtered by CoreBluetooth (known, Android-first rollout) | documented |

## 4) Regression — four previously-fixed launch bugs

| Bug | Status | Evidence |
|-----|--------|----------|
| OTP UX + rate limit (5/10min, 45s cooldown, trilingual 429) | **PASS(proven)** | test_auth rate-limit suite green in the 204 |
| Punch hard gate (GPS/BT strict guard) | code EXTENDED (perm row added), not removed; web pass-through unchanged | guard render verified (web); toggles → **DEVICE** |
| Escalate in-modal | untouched; backend escalate tests green | **PASS(proven)** |
| Camera hardening (auto-request, watchdog, retry) | untouched (`SelfieCamera`, in-screen camera handling intact) | **PASS(by-inspection)** + **DEVICE** smoke |
| Mobile app boots (web smoke) | language picker renders, no crash from new code | **PASS(proven)** — screenshot |

## 5) FIELD RE-TEST PROTOCOL — ~20 minutes at the factory

Preconditions: backend deployed (incl. this pack), geofence 19.313483/74.709384/1200 (already live),
6 beacons broadcasting, v1.0.11 installed on ≥2 phones (at least one Android 12+; one Android ≤11 if available).

1. **[2 min — Android 12+ phone, fresh install]** Login → Home → Punch In.
   ✔ Guard checklist shows: Camera / Location permission / GPS on / **Nearby devices permission** / Bluetooth on.
   ✔ NO "Continue anyway" button anywhere. Tap Allow on every row → selfie camera opens.
2. **[3 min — at Main Gate, beacon minor 33]** Take selfie → submit.
   ✔ Result screen: **Verified+** badge, zone **Main Gate**.
   ✔ Webdash → More → Attendance: row shows verified_plus; stored `ble_beacon_id=ibeacon:01122334-...-eff0:1:33`, `ble_zone=Main Gate`.
3. **[2 min — same phone]** Punch In again → ✔ "Already punched in today" toast, no duplicate row.
4. **[3 min — 2nd phone, walk ~100 m from any beacon but inside the site]** Punch.
   ✔ Result: **Verified** (green, no zone) — GPS inside, no beacon in range. (If a beacon IS heard, Verified+ with its zone is equally a pass.)
5. **[2 min — deny test, Android 12+]** Settings → Apps → HogoPlus → Permissions → Nearby devices → **Don't allow**. Open Punch In.
   ✔ Guard blocks; "Nearby devices permission" row ✗ with **Allow/Open Settings**. Grant again → unblocks without restart.
6. **[3 min — near Weighbridge, minor 18]** Report Complaint → ✔ same strict guard gates the camera → capture photo → submit.
   ✔ Incident detail card shows **📍 Zone: Weighbridge**; webdash incident modal shows it too.
7. **[2 min — outside beacon range]** Report another complaint → ✔ submits normally, NO zone line, no new blocking.
8. **[1 min]** Toggle **Bluetooth OFF** → open Punch In → ✔ blocked ("Bluetooth turned on" ✗); BT ON → auto-unblocks in ≤3 s. Repeat once on Report Complaint.
9. **[1 min]** Toggle **Location OFF** → both flows blocked the same way. Back ON.
10. **[1 min — Time Office phone/webdash]** Approvals → Attendance: any `reference_bootstrap` rows from today's supervised first punches show punch selfie + reference side-by-side → **Approve**.
11. **(optional +2 min)** Airplane mode ON (keep BT on) → punch → ✔ "Will retry" outbox chip → airplane OFF → auto-uploads → row appears.

**What each stored row must contain (spot-check via webdash):** step 2 → `verified_plus / zone / beacon ref`; step 4 → `verified`, no flag; step 6 incident → `ble_zone` set; step 7 incident → `ble_zone` null; no row anywhere flagged `outside_geofence` while physically on site.

## 6) SHIP MATRIX — deploy-only vs APK

| Item | Vehicle |
|------|---------|
| A — beacon wins ladder | backend deploy (ALREADY DEPLOYED, c0c08c9) |
| C2 backend — `ble_zone` in feed/department payloads | **backend deploy (tonight)** |
| C2 webdash — Department modal zone | **same deploy** (Docker multi-stage rebuilds webdash) |
| Ghost-reference hardening | **backend deploy (tonight)** |
| B — manifest (`neverForLocation` removed), LowLatency 10 s early-exit scan, fail-closed Nearby permission (primer + capture) | **v1.0.11 APK/AAB** |
| C1 — incident strict gate | **v1.0.11 APK/AAB** |
| version 1.0.11 / versionCode 10011 / iOS build 1.0.11, package com.hogoplus.fs unchanged | **v1.0.11 APK/AAB** |

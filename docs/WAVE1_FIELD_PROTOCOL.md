# v1.0.19 — WAVE 1 FIELD TEST PROTOCOL (on-device, factory)

Install the v1.0.19 APK on a real Android phone. Do the autopsy first (§C).

## A. SECURITY flow — do this AT THE MAIN GATE with a beacon in range
1. Log in as a real SECURITY employee (any watchman/clerk).
   ⚠️ Until you flip the flags (§D) real accounts see the OLD home — flip flags first
   or test with the demo bubble (+91 90000 00011, OTP 123456).
2. Home must show the new Security layout: big "Vehicle entry" button on top,
   count tiles (In today / Inside now), Gate log, Incident, Sahayak.
3. Tap Vehicle entry → New entry screen:
   a. ANPR path: tap "Photo of number plate", shoot a real plate → number should
      pre-fill within ~3 s and show "✓ Number read from photo". Note WRONG reads.
   b. Manual path: clear the field, type a plate by hand — confirm the keyboard
      does NOT cover the input (keyboard fix rides this build).
   c. Pick type (tractor), purpose (ऊस), leave driver empty.
   d. Gate zone chip must show your gate's beacon zone (e.g. "Main Gate 33")
      within ~6 s. Note if it stays "Finding gate…".
   e. Mark IN. → toast "नोंद झाली".
4. Gate log: entry appears at top with IN chip and your gate zone.
5. OUT pairing: new entry, same plate, Mark OUT → "Inside" tab must drop it.
6. OFFLINE: enable airplane mode → create an IN entry → must toast
   "नेटवर्क नाही — जतन झाले…" → disable airplane mode → wait ~1 min → entry
   appears in the gate log EXACTLY ONCE (no duplicate).
7. Timing: full entry (photo → saved) should be ≤ 30 s. Note your actual time.

## B. TIME OFFICE — any TO manager/clerk account
1. Home must show: Registrations / Flagged punches / Form approvals / No phone
   tiles WITH live numbers, and the big "Approval queue" button.
2. Tap a tile with a number > 0 → must land on the right queue.

## C. APK autopsy greps (before installing)
```bash
unzip -o app-release.apk -d apk_out > /dev/null
# version
grep -a "1\.0\.19" apk_out/AndroidManifest.xml || aapt dump badging app-release.apk | head -2   # versionName 1.0.19 / code 10019
# wave-1 screens & framework in the JS bundle
BUNDLE=$(ls apk_out/assets/index.android.bundle)
grep -ac "config-home" $BUNDLE            # >0  (widget framework)
grep -ac "vehicle-new-screen" $BUNDLE     # >0  (vehicle entry screen)
grep -ac "vehicles/log" $BUNDLE           # >0  (API wiring)
grep -ac "home/config" $BUNDLE            # >0
grep -ac "translate-with-padding" $BUNDLE # >0  (keyboard pack)
grep -ac "share-timings-button" $BUNDLE   # >0  (perf card share)
grep -ac "videoBitrate" $BUNDLE           # >0  (2 Mbps cap)
# BLE permissions still intact (config plugin)
grep -a "BLUETOOTH_SCAN" apk_out/AndroidManifest.xml   # present, WITHOUT neverForLocation
```

## D. Going live for real users (backend only, no build)
1. Flip flags as CGM (webdash login or curl):
   `PATCH /api/admin/settings {"home_config_enabled": true, "vehicle_log_enabled": true}`
2. (Optional, recommended after a quiet day) `{"notif_batching_enabled": true}` —
   enables the 30-min roll-up + 22:00–06:00 quiet hours for registration/approval pushes.
3. Changing any department's home later: `PUT /api/admin/home-configs` — layout
   changes ship instantly, no APK.

## E. Notifications on a real device (one of each)
1. Vehicle >12 h: leave a test IN entry overnight → Security manager gets the
   "🚚 वाहन १२ तासांहून जास्त आत आहे" push next morning (hourly sweep, 1/day/vehicle).
2. Registration pending: self-register a spare SIM → TO manager + CGM push.
3. Incident assigned/escalated/resolved: existing flows — verify tap opens the
   incident directly.
4. Approval pending: submit any dept form → approver push; tap opens submission.
5. If a push doesn't arrive: the Alerts tab is the source of truth — check it,
   then send me the phone's notification permission state.

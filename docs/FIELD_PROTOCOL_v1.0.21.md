# FIELD PROTOCOL — v1.0.21 (factory floor, run in order)
Every step: DO → EXPECT. Steps marked **⛔ GATE** are go/no-go: a GATE failure stops the
rollout at that point (features already gated PASS remain usable; do NOT bump the
app-version row until ALL gates pass). Non-gate failures: note and continue.

**You need:** the APK file on a laptop (`aapt2`, `unzip`), SSH to EC2, your owner phone,
one worker phone (Marathi speaker), one security-gate phone, a manager/Time Office
account, and the paper/Time Office register for last month.

---

## PHASE 0 — artifact autopsy (laptop, before ANY phone)

**1.** `aapt2 dump badging HogoPlus.apk | grep -E "versionName|versionCode"`
→ EXPECT `versionName='1.0.21'`, versionCode ≥ 10021 (record the actual code).

**2.** `unzip -p HogoPlus.apk assets/index.android.bundle | strings | grep -c "api.hogoplus.in"`
→ EXPECT a number ≥ 1.

**3.** `unzip -p HogoPlus.apk assets/index.android.bundle | strings | grep -E "preview\.emergentagent|localhost:8001|10\.0\.2\.2"`
→ EXPECT zero lines of output.

**4.** `aapt2 dump xmltree HogoPlus.apk --file AndroidManifest.xml | grep -A1 BLUETOOTH_SCAN`
→ EXPECT no `usesPermissionFlags` line (BLE regression check).

**⛔ GATE 0:** steps 1–4 all pass. Fail → do not install anywhere; send me the failing output.

---

## PHASE 1 — backend readiness (EC2, before ANY phone)

**5.** `grep '^DATABASE_URL' /opt/hogoplus/.env`
→ EXPECT host `*.rds.amazonaws.com` (NOT neon.tech).

**6.** Deploy per AUTOPSY §2 (git pull → OPENAI_API_KEY into .env → `docker compose up -d --build` → `alembic upgrade head`), then:
`docker compose exec api alembic current`
→ EXPECT `0015`.

**7.** `docker compose logs api | grep "AI CONFIG" | tail -1`
→ EXPECT `key_source=openai-dedicated`. If it says `emergent-universal-FALLBACK`, the key
didn't load — fix `.env`, `docker compose restart`, re-check.

**8.** Route smoke:
`curl -s -o /dev/null -w '%{http_code}\n' https://api.hogoplus.in/api/attendance/mine`
→ EXPECT `401` (route exists, demands auth). `404` = old code still running.

**9.** `docker compose logs api | grep "Uploaded DB backup" | tail -1`
→ EXPECT a line < 4 h old (backup job alive on the new image).

**⛔ GATE 1:** steps 5–9 all pass. Fail → no phone installs until fixed.

---

## PHASE 2 — install & login (owner phone first)

**10.** Install the APK OVER the existing 1.0.20 (no uninstall).
→ EXPECT app opens, still logged in (or normal OTP login works), home loads with your tiles.

**11.** Profile → check version.
→ EXPECT 1.0.21.

**⛔ GATE 2:** both pass. Fail → screenshot + stop.

---

## PHASE 3 — voice-first reporting (worker phone, Marathi speaker, near running machinery)

**12.** Install on the worker phone, log in as the worker. Open incident report (camera
opens first) → take any photo → on the form, EXPECT the "Speak your report" mic section
ABOVE the typing box.

**13.** Hold the mic, speak ~10 s in Marathi (e.g. "पंप नंबर दोन जवळ पाणी गळत आहे"), release.
→ EXPECT "Listening and writing…" then, within ~10 s, the description fills in Marathi
with an AI chip, plus the "Did we hear you right?" hint. Meaning must be right;
letter-perfect spelling is NOT required.

**14.** Edit one word of the filled text.
→ EXPECT the AI chip disappears (your edit wins).

**15.** Submit the report.
→ EXPECT normal success screen; open the incident → description is the voice text.

**16.** Airplane mode ON → new report → photo → hold mic, speak, release → submit.
→ EXPECT "Voice saved — it will be written after sending." and the report queues in the
outbox. Airplane mode OFF → wait for sync → open the incident → EXPECT the description
filled from your voice, and a `voice_transcribed` entry in its timeline.

**⛔ GATE 3:** 13, 15 and 16 pass (14 is a note-only check).

---

## PHASE 4 — read-aloud TTS (worker phone)

**17.** Alerts tab → tap the 🔊 on any alert row.
→ EXPECT spoken audio of that alert (loading spinner first time), in the app language.

**18.** Tap the same 🔊 again after it finishes.
→ EXPECT playback starts near-instantly (cached — no synth wait).

**19.** Airplane mode ON → tap the SAME alert's 🔊.
→ EXPECT it still plays (offline cache). Tap a DIFFERENT, never-played alert →
EXPECT "No internet — this audio is not saved yet." — no crash. Airplane mode OFF.

**20.** Open the incident from step 15 → AI assessment card → 🔊.
→ EXPECT Marathi audio for a Marathi-language user.

**⛔ GATE 4:** 17 and 19 pass.

---

## PHASE 5 — My Month vs the Time Office register

**21.** Worker phone → attendance history → "📅 My Month" card.
→ EXPECT days present, late days, and "Last month: N days present" all visible.

**22.** Pick 2 more workers of different shifts (one must be C-shift/night). For all 3,
compare the app's month numbers against the Time Office register.
→ EXPECT exact match, including night-shift punches counting for the shift's start day
and 15-min grace on lateness.

**⛔ GATE 5:** all 3 workers match exactly. Any mismatch → send me emp_id + month +
register value vs app value; do NOT announce the feature to workers yet.

---

## PHASE 6 — attendance regularization (worker + manager)

**23.** Worker phone → attendance history → find a flagged/wrong punch row → tap
"This is wrong" → speak or type a short reason → send.
→ EXPECT "Sent to Time Office" and the row now shows "Under review".

**24.** Same row → try "This is wrong" again.
→ EXPECT blocked — one open request per punch (server-enforced).

**25.** Manager phone → Approvals tab → "Attendance dispute" queue.
→ EXPECT the dispute card with punch details, "Worker says" text and/or ▶ voice note that
plays.

**26.** Approve it (with a short note).
→ EXPECT worker gets a notification; the row on the worker phone now shows "Corrected ✓".

**⛔ GATE 6:** 23–26 all pass.

---

## PHASE 7 — same-as-last (security gate + any form user)

**27.** Security phone → vehicle entry → log any vehicle IN (normally). Then start a
SECOND entry.
→ EXPECT "⏮ Same as last entry · X min ago" chip; tapping it pre-fills plate/purpose/
driver with "Same vehicle? {plate}" confirm; adjust direction, save. Total ≤ ~4 taps.

**28.** Open a routine gauge/checklist form previously submitted by this user → tap
"Fill like last time".
→ EXPECT last submission's values fill in with a "copied" chip; "Copied — check and
submit"; edit one value; submit works.

**⛔ GATE 7:** both pass.

---

## PHASE 8 — duplicate detection (two phones, same zone)

**29.** Worker phone: report an incident (e.g. leak, zone X). Within a few minutes,
from the OTHER phone, report the SAME kind of incident in the SAME zone.
→ EXPECT the second incident's detail shows "Grouped with an earlier report of the same
issue" + "View first report" linking to the first. Submission itself is NEVER blocked.

**30.** On the grouped one, tap "Not same — unlink".
→ EXPECT "Unlinked", banner gone, both incidents standalone.

**31.** Report a THIRD incident in a DIFFERENT zone or >30 min later.
→ EXPECT no duplicate banner.

**⛔ GATE 8:** 29 and 30 pass (31 is a note-only check).

---

## PHASE 9 — keyboard spot-check (your 5-minute pass, P2 — NOT a gate)

**32.** On the smallest-screen phone available, with keyboard open, check the field is
never hidden and the submit button stays reachable on: (a) incident description typing
fallback, (b) regularization dispute note, (c) vehicle driver-name field, (d) any form's
last numeric field, (e) login OTP box.
→ EXPECT no field hidden behind the keyboard, no jumping. Note any failure with screen
name + phone model (fix rides the next build; not a rollout blocker).

---

## PHASE 10 — rollout

**33.** All gates 0–8 green → on EC2, bump the app-version row to 1.0.21
(AUTOPSY §2 last step).
→ EXPECT 1.0.20 phones show the update banner and self-update. Rollout complete.

**Report back:** gate number + step number + what you saw for anything red. One line per
failure is enough.

---

## ADDENDUM — if your build was cut AFTER the v1.0.22 batch landed (2026-07-30)

The repo moved to **v1.0.22** right after the v1.0.21 docs were written (owner-approved
next batch: punch-out nudge, swap FOR UPDATE, outbox idempotency — all additive).
If `git pull` / the build happened after that:
- Step 1: expect `versionName='1.0.22'`, versionCode ≥ 10022.
- Step 6: expect `alembic current` → **0016** (0016 adds only `client_uuid` columns on
  incidents/form_submissions — additive, applies in <1 s).
- Everything else in the protocol is unchanged. All 33 steps and gates apply as written.

**PHASE 11 — punch-out nudge (v1.0.22 only, needs one shift boundary; NOT a gate)**

**34.** Pick a worker who punched in but does NOT punch out at shift end. ~15–30 min
after their shift end (sweep runs every 15 min), their phone gets
"पंच आउट करायला विसरलात?".
→ EXPECT tapping the notification lands directly on the punch screen; one tap punches out.

**35.** For a worker who ignores the nudge: ~2 h after shift end (env-tunable
`PUNCHOUT_FLAG_AFTER_HOURS`, default 2) the day appears in the Time Office flagged
queue with reason "No punch-out after shift", and the worker gets the transparency
notification ("sent to Time Office — nothing is decided automatically").
→ EXPECT: NO punch-out time was invented anywhere; the punch-in verification level is
unchanged; the worker's history row shows "✋ This is wrong" (dispute) on that day.

**36.** Let a third worker punch out LATE (after the flag).
→ EXPECT the flag clears itself; the row leaves the Time Office queue without any action.

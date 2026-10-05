# MORNING.md — 2026-10-06, overnight work

Everything below is **app + tooling code only**. The production server was not
touched: no deploy, no migration, no restart, no settings or DB write, no `.env`
change. `api.hogoplus.in` is exactly as you left it (schema 0023, 1 worker,
face ON, plate ON, ar_distance ON, plate_scale OFF, broadcasts OFF).

---

## What you do (about 10 minutes of your time)

1. Import the repo into the build workspace (the other agent's environment) and
   press **Build**. Nothing else needs to change there — no new dependency, no
   new permission, no manifest change.
2. Install the APK on your phone.
3. Run the five checks in "What to test" below.
4. Tell me what you see. If the AR crosshair now lands under your finger, I will
   tighten the numeric thresholds with real data from your device.

> The Android native module changed (2 lines in `ExpoArDistanceView.kt`). I could
> not compile Kotlin here — there is no Android SDK on this Mac — so **the build
> itself is the first compile**. If it fails there, revert that one hunk
> (`currentDisplayRotation()` → `0`) and everything else still works.

---

## 1. AR distance — root cause and fix

### Your hypothesis was close, but not what the code does

You suspected window/page coordinates versus a view that starts lower (status
bar + header + safe-area). **Disproved on this screen**: the capture screen is
full-bleed with no header (`app/incident/capture.tsx:487`), the handler already
used `locationX/locationY` (which React Native reports relative to the pressed
view, not the window), and it already used `onLayout` instead of
`Dimensions.get("window")`.

### What was actually wrong

`ArDistanceOverlay` has two different rectangles and the code mixed them up:

| rectangle | size | what it is |
|---|---|---|
| overlay / AR preview | full screen, e.g. 412 × 915 dp | what the crosshair and the native camera use |
| touch layer | 412 × 659 dp (`bottom: "28%"`) | stops above the shutter so the buttons stay tappable |

The old handler divided `locationY` by the **touch layer's** height, and then
handed that fraction to two consumers that both read it as a fraction of the
**full preview**: the crosshair (`left/top` in % of the full-size overlay) and
`setTarget()` → ARCore. Result: every tap was scaled by 1 / 0.72 = **1.39×**.

- Tap 300 dp down a 915 dp screen → crosshair drawn at 417 dp: **117 dp (≈2 cm)
  below your finger**, and the error grows the lower you tap.
- The depth sample was taken at that same wrong point, usually the floor or a
  wall behind your target — which is why the number was "wildly wrong" and
  jumped around as the wrong pixel moved.

One bug, both symptoms.

### Native was not at fault

I traced the whole chain on both platforms. ARCore
`transformCoordinates2d(VIEW → TEXTURE_NORMALIZED)`
(`ExpoArDistanceView.kt:236-252`) and ARKit
`displayTransform(for:.portrait).inverted()` (`ExpoArDistanceView.swift:149-152`)
already handle display rotation and the aspect-fill crop, and both expect a
0..1 fraction of the preview. They were being fed a wrong fraction.

### What I changed

- **`src/ar/tapMapping.ts`** (new, pure): maps a touch from touch-layer-local
  coordinates to a fraction of the AR preview's **own measured frame**. Window
  dimensions are never used. If either frame has not been measured yet it
  returns `null` and the tap is ignored — a guess puts the crosshair somewhere
  you did not touch.
- **`ArDistanceOverlay`**: measures the preview frame and the touch-layer frame
  separately and maps through that helper.
- **Convergence gate** (`distanceFilter.ts`): no number is shown until the
  rolling window holds **≥ 3 samples** *and* their spread is within
  `max(0.1 m, 8% of the distance)` for LiDAR/depth, `12%` for plane/point/feature.
  This closed a real hole: a **single** sample has a spread of exactly 0 by
  definition, which used to pass the confidence check and print a confident
  wrong number off one frame.
- **Hints instead of numbers**: new `converging` ("Hold still — measuring") and
  `unstable` ("Readings disagree — hold steady or aim at an edge") in EN/HI/MR.
  Poor tracking or no texture → hint, blank number. A blank is correct.
- **± uncertainty** is now shown on approximate readings too, not just exact
  ones (`≈ 20.1 m ±0.2`).
- **Captured measurement held to the same bar** (`captureMeetsBar`): the native
  layer resolves a capture from whatever its window holds — including one
  sample — so an unconverged distance was being **saved on the incident and
  shown to a manager in the MD dashboard** even while the camera correctly
  showed nothing. It is now dropped (the diagnostics are kept).
- **Debug dot + HUD visible to everyone** (`src/ar/debugAccess.ts`): your own
  account is `0001 / Manager / rank 3`, which the old `rank <= 2` gate locked
  out. The rank and server-allowlist logic is intact behind one constant —
  set `AR_DEBUG_FOR_EVERYONE = false` to restore the real gate.
- **HUD additions**: the tap fraction actually sent to native, and whether the
  window has converged.
- **`ExpoArDistanceView.kt`**: passes the real display rotation to
  `setDisplayGeometry` instead of a hardcoded `0`. Identical behaviour on a
  portrait-locked phone; correct on a naturally-landscape device (tablet).

---

## 2. Accuracy bench for plates and faces

`backend/scripts/plate_face_bench.py` + `BENCH_README.md`. Runs the **exact**
server pipeline over a folder of your photos and writes `results.csv` plus
`crops/` so you can eyeball every detection. It imports no config, no database
and no storage, and makes no network calls.

Easiest run, on the EC2 box, with the script bind-mounted into the existing
image (do **not** rebuild — the image predates the script):

```bash
sudo docker run --rm --network none --cpus 1.5 --memory 2g \
  -v /home/ubuntu/photos:/data:ro -v /home/ubuntu/bench-out:/out \
  -v /opt/hogoplus/backend/scripts/plate_face_bench.py:/app/backend/scripts/plate_face_bench.py:ro \
  hogoplus-backend:latest python scripts/plate_face_bench.py /data --out /out --limit 10
```

`--network none` proves it cannot reach the database. Start with `--limit 10`:
it is the live 4 GB box. A local Mac recipe is in the README.

The column to trust most is **`normalise_fixes`** — when it is not empty, the
OCR text was not a legal plate and only became one after character repairs, so
that row is weaker than its confidence suggests.

---

## 3. Indian plate normalisation

Rewritten around an explicit layout table: standard plates with 1–2 digit RTO
and 1–3 letter series, **BH-series** (`22BH1234AA`), `IND` stickers, missing or
extra separators, lowercase and surrounding junk words. Confusable repairs
(O↔0, I↔1, Z↔2, S↔5, B↔8 …) are applied **only** where the layout demands that
character class, and every repair is recorded: `normalize_plate_detail()`
returns `{raw, candidate, normalised, format, state, fixes[]}` with the model's
raw read never modified. `normalize_plate()` keeps its old signature.

It now **refuses** rather than guesses: unknown state codes, wrong tail length,
phone numbers, dates, plain words, and anything needing more than 3 repairs. One
deliberate trade: a misread Delhi-style 3-letter plate returns nothing instead
of a plausible-looking wrong plate.

> ⚠ **This runs on the backend, so it does nothing in production until the
> backend is redeployed.** I did not deploy it. Say the word and it is the usual
> pull → build → `up -d` (no migration, no flag).

---

## What to test on the device

| # | Test | What good looks like |
|---|---|---|
| 1 | Open Report Complaint, tap an object | The **+** appears **under your fingertip**, not below it. Tap high, middle, and just above the shutter — the error used to grow as you went lower. |
| 2 | Watch the pink debug ring | It should sit **on** the crosshair. That ring is the point ARCore actually sampled, back-projected — crosshair and ring together means the whole chain is aligned. |
| 3 | Measure something you can tape-measure (a door, a pillar at 2 m and 5 m) | A number only after a moment of holding still, and within roughly 10% of the tape. If it is off by a constant factor, use Calibrate in the HUD. |
| 4 | Point at a blank wall, or wave the phone around | **No number at all** — just "Hold still — measuring" or "Readings disagree". Blank is the correct answer; tell me if you ever see a number here. |
| 5 | Take a photo after a good reading, then open the incident in the dashboard | The stored distance should match what the camera showed. After a bad/unstable reading, the incident should carry **no** distance rather than a wrong one. |

Also worth a minute: the debug HUD is now visible on your own account without
any role change, and the AR calibration screen opens from it.

---

## Verified vs unverified

**Verified here**
- 41 unit tests (`node --test frontend/src/ar/__tests__/*.test.ts`): the tap
  mapping with realistic device numbers (including the exact 1.39× regression,
  an inset touch layer, a preview that is not the window, and a
  landscape-shaped preview), the convergence gate, the one-sample trap, the
  capture bar, and the debug gating in both modes.
- `tsc --noEmit` clean, `expo lint` clean (2 pre-existing warnings in
  `arDistance.ts`, untouched), i18n parity 656 keys × 3 languages, screen-header
  guard passes.
- Plate normalisation: 17 new tests plus **all 21 pre-existing assertions** from
  `test_prompt9_anpr.py` and `test_ux_pack.py` re-run verbatim on python3.12.
- Bench tool: 49 tests, plus a real run over `backend/uploads` (face detected at
  0.937, corrupt PNG handled without aborting).

**Only a device can prove**
- That the crosshair lands under the finger on real hardware — the mapping is
  right in arithmetic, but only ARCore on your phone closes the loop.
- Whether the Kotlin change compiles (no Android SDK here) and whether the real
  display rotation behaves as expected.
- Real-world measurement accuracy, and whether `MIN_SAMPLES = 3` with an 8%
  spread band feels responsive or sluggish in the factory. These are two
  constants in `distanceFilter.ts`; tell me how it feels and I will tune them.
- Plate OCR accuracy on real vehicles — that is what the bench tool is for.
- iOS: unchanged and unverified. The app ships on Android today.

---

## Open items (nothing urgent, nothing blocking your build)

- `OPENAI_API_KEY` on the server is still a **masked value pasted by mistake**
  (`sk-proj-…A...`, 178 chars, ends in literal dots) so OpenAI returns 401. Face
  and plate detection are local ONNX and unaffected, but AI classification,
  voice-to-text reporting and read-aloud are dead until a real key is set.
- The plate normalisation improvement needs a backend deploy to take effect.
- `webdash/package-lock.json` is still not committed although the Dockerfile
  needs it; builds work only because an untracked copy sits on the EC2 box.
- The repo's `docker-compose.yml` still has redis commented out. Production is
  covered by an untracked override file I added; a fresh clone is not.
- Sahayak answers "not found" because 0 SOP documents are loaded.
- Your account `0001` is Manager/rank 3 in the live DB while the PRD says CGM.

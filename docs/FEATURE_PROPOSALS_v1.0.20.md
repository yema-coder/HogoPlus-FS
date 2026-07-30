# FEATURE PROPOSALS — independent list (no code yet), v1.0.20 planning
Ranked by (value to factory people ÷ effort). Effort: S ≤1 day · M 2–3 days · L ≥1 week.

## Worth building — ranked
1. **Shift-end auto-punch-out nudge (S).** If a worker is still "inside" 30 min after shift
   end, push "बाहेर पडताना पंच करा". Kills the #1 attendance dispute (forgotten punch-outs);
   uses existing scheduler + zone data.
2. **Manager morning digest (S).** One 7 AM notification per manager: present/absent count,
   open incidents, pending approvals. Replaces the morning webdash ritual on a phone that's
   already in their pocket.
3. **Offline-first forms parity (M).** Punch + incidents already queue offline; gauge/checklist
   forms still need network. Factory dead zones (boiler basement) make this a real daily loss.
4. **Voice-first incident for workers (M).** Hold-to-talk → Whisper transcript → AI fills
   category/severity → worker confirms. Reading/typing drops to zero; pairs with UX proposal C1.
5. **Cane-truck pre-registration "expected today" (M).** Already on your Wave-2 list — gate
   security matches an expected list instead of typing plates; queue time at the gate drops.
6. **Attendance anomaly flags for Time Office (M).** Auto-flag impossible pairs (punch-in
   with no punch-out, both outside geofence, device changed mid-day) into the existing
   flagged-attendance queue — Time Office stops eyeballing raw logs.
7. **Beacon health board (S).** Beacons die silently; last-seen timestamps already land in
   diagnostics. A red tile when a zone is >24 h silent saves ghost "BLE broken" tickets.

## NOT worth building (my honest take)
- **In-app chat/messaging** — WhatsApp owns this; you'd build a worse WhatsApp and split comms.
- **Gamification/leaderboards for attendance** — punitive vibes in a factory, gaming risk, zero
  work reduction.
- **Worker-facing analytics dashboards** — workers need 3 numbers max (my shifts, my punches,
  my requests); dashboards are manager food.
- **Custom report builder in webdash** — the nightly PDF + 3 fixed views cover the real asks;
  a builder is an L-effort toy that gets used twice.
- **iOS build right now** — your fleet is Android; TestFlight admin overhead for ~2 phones
  isn't worth it until a director insists.

Send your list — I'll merge, re-rank against effort, and mark conflicts.

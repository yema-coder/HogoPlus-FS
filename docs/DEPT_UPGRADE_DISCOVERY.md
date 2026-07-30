# DEPARTMENT UPGRADE — RAPID DISCOVERY (Part A)

Source of truth: live Neon DB, 2026-06. 13 departments, 6 roles (MD>CGM>Manager>Staff>Clerk>Worker).
Real active headcount ≈ 401. Everything marked **[ASSUMPTION]** needs client verification —
all else is read from the DB or the codebase.

Legend: effort S = hours, M = 1–2 days, L = 3+ days. "CONFIG" = after Wave-1 framework
ships, done via backend/config only (no APK).

---

## Existing capability inventory (what we reuse, zero new code)

| Capability | Where | State |
|---|---|---|
| ANPR (plate OCR + Indian-plate validation + confusable fix) | `POST /api/ai/anpr`, `app/anpr.py`, `AnprTextInput` | LIVE |
| Push + trilingual templates + demo-bubble isolation | `app/notify.py` dispatcher | LIVE |
| In-app inbox (Alerts tab) + unread badge | `notifications` table, `/api/notifications/mine`, `(tabs)/alerts` | LIVE |
| Push deep-links (incident → detail, else Alerts) | `usePushSetup.ts` | LIVE (needs more routes) |
| Offline outbox with retry | `src/offline/outbox` | LIVE |
| BLE zone session (gate zones incl. Main Gate, Weighbridge) | `zoneSession.ts`, 29 active beacons | LIVE |
| Feature flags | `settings` table (beacon_first_mode pattern) | LIVE |
| Forms engine (13 dept forms) + voice fill + photo/gauge AI | forms engine | LIVE |
| Webdash (Overview/Approvals/Attendance/Incidents/Reports/Admin) | `webdash/src/screens` | LIVE |

## ⚠️ Conflicts / flags found in the DB (per your rule, flagged BEFORE building)

1. **SECURITY already has a `gate_entry` FORM** (entry_type/person_or_plate/id_photo/purpose,
   nearly zero submissions). It cannot do IN/OUT pairing, currently-inside, or a register view.
   **Proposal:** new structured vehicle log (Wave 1) becomes the VEHICLE path; the existing
   form stays for PEOPLE/visitors only (rename "Visitor entry"). → building vehicle log as
   ordered; form rename is CONFIG (needs your yes).
2. **Push tokens:** only **1 real employee** has a push token today (builds register tokens on
   login). Wave-1 evidence for "notification received on a real device" is therefore only
   possible on YOUR device; for everyone else the in-app inbox is the record until they
   update to a build that registers tokens (v1.0.15+ does).
3. "Bootstrap confirmations" on the TO home — I interpreted as the **flagged-attendance
   review queue** (already in Approvals) + **phone-less seeded employees** (6 rows,
   onboarding_status='seeded') needing phone fill. **[ASSUMPTION — confirm meaning.]**
4. Gate zone auto-tag needs the gate phone to be a real build with BLE — Expo-web/testing
   can't scan. Field protocol covers it.

---

## Department blocks

Format: (1) daily job & paper habits → (2) where app fails them → (3) proposed home
(3–6 primary actions + live info) → (4) config vs code + effort.

### SECURITY — 43 (31 Watchmen, 3 Jamadar, 6 Clerks, 1 Manager)
1. Man gates 24×7 in 3 shifts: log every vehicle+visitor (paper *gate register*), night
   patrols, weighbridge gate control. **[ASSUMPTION: paper register format = serial no,
   plate, party, purpose, in/out time, signature].** WhatsApp photos of suspicious vehicles
   to the HOD.
2. App gives them punch+incident only; their PRIMARY job (gate register) is still paper;
   generic `gate_entry` form is typing-heavy, no in/out pairing, no register view.
3. **Home:** 🚚 Vehicle entry (primary, huge) · 🚶 Visitor entry (existing form) · ✅ Punch ·
   🚨 Incident · Live: today's gate log count + currently-inside count + my zone chip.
4. Vehicle log = **CODE (L, Wave 1)**. Home layout = CONFIG after framework. Visitor form
   rename = CONFIG (S).

### TIME_OFFICE — 6 (3 Managers incl. HR Manager Kale, 3 Clerks)
1. Attendance ledger keepers: registrations, muster corrections, OT capture, shift changes.
   Paper musters + biometric reconciliation. **[ASSUMPTION: they reconcile against a legacy
   biometric report daily].**
2. Their work is scattered across Approvals tab, employee directory, OT form — no single
   "work queue"; no counts visible until they open each tab.
3. **Home:** 🧾 Pending registrations (count + one-tap queue) · 🚩 Flagged attendance
   (count + queue) · 👤 Employee search / ➕ direct-add · 📵 Phone-less employees (6 seeded
   rows) fix-list · ⏱ OT capture form. Live: today HC present **[ASSUMPTION: present-count
   API exists via dashboard]**.
4. All = **CONFIG** on the framework + one S widget (counts endpoint) — Wave 1.

### ENGINEERING — 207 (50 Helpers, fitters/welders/boiler/turbine crews, 4 Managers)
1. Breakdown + preventive maintenance across mill/boiler/power-house; job cards on paper;
   verbal breakdown reporting; store indents for spares. Largest department.
2. Semi-literate helpers face a text-heavy job_card form; no "my assigned jobs" view; no
   breakdown-severity fast path (incidents work but aren't framed as breakdowns).
3. **Home (Worker):** 🔧 Report breakdown (photo-first incident, machine pick-list) ·
   📋 My job cards · ✅ Punch · 📖 Sahayak. **Home (Manager):** open breakdowns by section ·
   job-card queue · manpower today.
4. Machine pick-list on incident = **CODE (M, Wave 2)**; job-card "my queue" = **CODE (M,
   Wave 2)**; homes = CONFIG.

### PRODUCTION — 50 (Panmen, Centrifugal operators, Chemists, Juice supervisors, 1 Manager)
1. Shift process readings every 1–2h (pan/centrifugal/evaporator logs) on paper sheets;
   chemist lab entries; handover notes at shift change.
2. `hourly_process_log` form exists but generic; no reminder cadence; no shift-handover
   artifact; gauge-photo AI exists but underused. **[ASSUMPTION: they still fill paper
   sheets in parallel].**
3. **Home:** 🌡 Hourly log (with next-due countdown) · 🔁 Shift handover note (voice) ·
   🚨 Incident · Live: last log time + due-in chip.
4. Due-countdown widget = **CODE (S, Wave 2)**; handover = **CODE (M, Wave 3)**; rest CONFIG.

### AGRICULTURE — 34 (13 Slipboys, 9 Fieldmen, 4 Overseers, 3 Cane Supply Officers)
1. Field staff on bikes across villages: cane surveys, harvest program slips (slipboys
   issue cutting slips), farmer liaison. Mostly OUTSIDE beacon coverage; worst network.
2. `field_visit` form exists; GPS field exists; but offline durability is their #1 need and
   photo upload on 2G fails. **[ASSUMPTION: slip issuance still fully paper & must stay
   paper for legal reasons this season].**
3. **Home:** 🌾 Field visit (offline-first, voice note) · 📋 My visits this week ·
   ✅ Punch (GPS-only accepted flow) · Live: pending outbox count front-and-center.
4. Outbox-count widget = **CONFIG** (widget exists in framework, S). Photo-quality
   downscale for 2G = CODE (S, rides the video-bitrate work, Wave 2).

### CANE_YARD — 6 (2 Kata Clerks — incl. 0061 Sunil, 2 Shift Supervisors)
1. Weighbridge (kata) operation: gross/tare weights per cane vehicle, slip issue; queue
   management in crushing season. Works WITH Security's gate flow.
2. `weighment_capture` form exists; no link between weighment and the vehicle's gate entry.
3. **Home:** ⚖️ Weighment capture · 🚚 Yard queue (vehicles IN at gate, not yet OUT — reuses
   Wave-1 vehicle log!) · 🚨 Incident. Live: today's weighments count.
4. Yard-queue widget reading vehicle log = **CODE (S, Wave 2)** — cheap win after Wave 1.

### STORE — 8 (Clerks + Helpers)
1. Material issue/receipt against indents; bin cards on paper; engineering is main customer.
2. `material_issue` form exists; no indent→issue linkage; no pending-indent view.
3. **Home:** 📦 Material issue · 📥 Pending indents **[ASSUMPTION: indents flow through
   Purchase's indent_review]** · Live: today's issues count.
4. Indent linkage = **CODE (M, Wave 3)**; home = CONFIG.

### PURCHASE — 2 (Manager + Staff)
1. Indents → quotations → POs; approvals over WhatsApp/phone.
2. `indent_review` form exists; no approval queue framing.
3. **Home:** 🧾 Indent queue · ✅ My approvals · Live: pending count.
4. CONFIG only (queue = existing submissions filter).

### ACCOUNTS — 17 (Clerks, 2 Cashiers)
1. Cane bills, salary, payment vouchers; ledger software exists outside this app.
   **[ASSUMPTION: no accounting integration wanted — app is for tasks/attendance only].**
2. `payment_note` form exists; little else needed by design.
3. **Home:** 🧾 Payment note · ✅ Punch · 📖 Sahayak. CONFIG only.

### GODOWN — 4 (Clerks)
1. Sugar bag stacking/dispatch counts (`bag_movement` form); coordination with Security on
   dispatch trucks.
2. No dispatch-truck visibility.
3. **Home:** 🧮 Bag movement · 🚚 Dispatch trucks today (vehicle-log filter, Wave 2 widget) ·
   Live: today's bags in/out. CONFIG + shared vehicle widget (S).

### CIVIL — 16 (Drivers, Clerks, Peons, Supervisors)
1. Building/road repairs (`repair_request`), vehicle drivers pool.
2. Fine as-is for wave 1.
3. **Home:** 🧱 Repair request · ✅ Punch · 🚨 Incident. CONFIG only.

### DISTILLERY — 2 (+ contract labour **[ASSUMPTION]**)
1. Batch logs (`batch_log`), safety-critical zone.
2. Fine for wave 1. **Home:** 🧪 Batch log · 🚨 Incident (critical default). CONFIG only.

### ADMIN — 11 (CGM, VP, Drivers, Clerks, Peons)
1. Management + grievances (`grievance` form) + vehicle pool drivers.
2. CGM already has manager card/dashboards.
3. **Home (CGM/MD):** 📊 Today's factory strip (present count, open incidents, pending
   approvals) · 📣 Announce · 🧾 Approvals · 🏭 Departments. Mostly CONFIG; factory strip
   widget = **CODE (S, Wave 1— reuses dashboard summary)**.

---

## NOTIFICATION EVENT MATRIX (full; ★ = Wave-1 build scope)

| Event | Who | Urgency | Delivery | Anti-spam rule |
|---|---|---|---|---|
| ★ Incident assigned to dept | Dept Manager (else CGM) | High | Push + inbox | 1 push per incident; further updates inbox-only |
| ★ Incident escalated | Target (mgr/CGM) + reporter (inbox) | High | Push + inbox | escalate-if-ignored: repeat push once after 4h unseen [flag-gated] |
| ★ Incident resolved | Reporter | Normal | Push + inbox | none (single event) |
| ★ New registration pending | TO Manager + CGM | Normal | Push + inbox | batch: max 1 push/30 min, "N pending" roll-up |
| ★ Approval pending (forms/attendance) | Responsible approver | Normal | Push + inbox | batch 30 min roll-up, quiet hours 22:00–06:00 (inbox always) |
| ★ Vehicle IN > 12h | Security Manager | Normal | Push + inbox | 1 per vehicle per day; sweep runs hourly |
| ★ Announcement | Audience | Normal | Push + inbox | already 1-shot; no repeat |
| Swap requested / accepted / approved | Target → requester → both | Normal | Push + inbox | existing flow; joins matrix in Wave 2 |
| Shift changed by TO | Affected employee | High | Push + inbox | immediate, no batching |
| Punch flagged (GPS/no-beacon/face) | Employee + TO Manager | Low | Inbox only | daily digest to TO |
| Process log overdue (Production) | On-duty operator | Low | Push | max 1/interval, only during their shift |
| SMS budget breaker tripped | CGM | Critical | Push + inbox | 1/hour max (design: OTP_IP_RATE_LIMIT doc) |
| Escalation SLA breach (48h) | CGM | High | Push + inbox | existing escalation sweep; joins matrix Wave 2 |
| Registration approved (welcome) | New employee | Normal | Push + inbox | single |
| App update available (force) | All | High | In-app gate (exists) | n/a |

Quiet hours + batching keyed off `settings` table so tunable without deploys.
Delivery reliability (Wave 1): token refresh on login (exists), push send retry ×3 with
backoff, inbox row written BEFORE push attempt (inbox is the source of truth).

## Wave plan

- **WAVE 1 (tonight):** config-home framework + Security vehicle log (app+webdash) + TO
  approvals-first home + ★ notifications + already-queued v1.0.19 items.
- Wave 2: Cane-yard yard-queue & Godown dispatch widgets, Engineering breakdown pick-list +
  my-job-cards, Production due-countdown, Agriculture photo downscale, swap/shift events
  into matrix.
- Wave 3: shift handover, store indent linkage, remaining matrix rows.

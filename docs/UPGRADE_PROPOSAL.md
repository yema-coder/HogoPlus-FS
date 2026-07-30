# HogoPlus-FS — Phase 2 Upgrade Proposal
### Post-Launch Product Roadmap for Prasad Sugar & Allied Agro Products Ltd

**Document version:** 1.0 · June 2026
**Baseline:** v1.0.14 (launch build, frozen)
**Prepared for:** Management, Prasad Sugar & Allied Agro Products Ltd

---

## 1. Executive Summary

HogoPlus-FS launches with a foundation that no off-the-shelf competitor can match today:

| Capability already LIVE in v1.0.14 | Why it matters |
|---|---|
| Trilingual app (Marathi-first, Hindi, English) built for semi-literate workers | Zero training barrier for the shop floor |
| 3-layer attendance verification: GPS geofence → **BLE beacon zones** → **AI face match** (AWS Rekognition) | Proxy-punching is effectively impossible |
| 3-tap complaint reporting with photo/video/voice note, watermarking, offline outbox | Incidents captured even with no network inside the plant |
| AI pipeline: automatic severity classification, **ANPR number-plate reading**, gauge reading, voice-to-form filling | The camera is already a data-entry device |
| Sahayak — RAG chatbot grounded on your own SOP documents | Institutional knowledge on every phone |
| MD Command Center web dashboard with live complaint feed, approvals aging, nightly trilingual PDF reports | Management visibility without asking anyone |
| Shift roster + swap workflow, escalation ladders, announcements, push notifications | Complete daily operations loop |

**The opportunity:** every module below **re-uses this same engine** — beacons, face AI, ANPR, the forms engine, and the RAG stack — so each new feature ships faster and cheaper than any competitor building from zero. This proposal turns HogoPlus-FS from a workforce app into the **operating system of the factory**.

The roadmap is split into three phases:

- **Phase 1 — Consolidate & Delight (Weeks 1–6):** the four features management asked for, plus post-launch hardening.
- **Phase 2 — Safety & Control (Weeks 7–16):** Safety Eyes goes deep; the plant becomes provably safer.
- **Phase 3 — The Intelligent Mill (Weeks 17+):** season-scale logistics, prediction, and payroll-grade data.

---

## 2. Phase 1 — Consolidate & Delight (Weeks 1–6)

> Goal: lock in the launch, ship the four management-requested features, and remove every rough edge reported from the field.

### 2.1 Dept Home Screens *(management-requested)*

Today every employee sees the same home screen. Phase 1 makes the home screen **belong to the department**.

- **Per-department tile layout** — each of the 13 departments gets a curated home: its most-used forms pinned first (e.g. CANE_YARD sees the vehicle/indent forms, ENGINEERING sees breakdown reporting, SECURITY sees gate registers).
- **Dept notice board** — the announcements system (already live) gains a persistent, department-scoped board on the home screen with read receipts, so HODs know who has seen the notice.
- **Dept snapshot strip** — a glanceable row for managers: present today / open complaints / pending approvals for *their* department, powered by the existing dashboard aggregates.
- **Shift-aware content** — home highlights differ for A/B/C shift (e.g. C-shift sees the punch-out reminder card earlier).

*Builds on:* existing tile grid, announcements fan-out, dashboard aggregate endpoints.
*Estimated effort:* **2 weeks** (mobile + small backend config table).

### 2.2 Registration Suite *(management-requested)*

Registration today covers a single new joinee with a selfie. The suite makes HogoPlus the **single source of truth for the workforce record** — critical as you scale 400 → 5,000.

- **Bulk & seasonal onboarding** — CSV/Excel import with dry-run preview for the crushing-season labour intake; auto emp-id suggestion (already built) applied in batch.
- **Document vault** — per-employee documents (Aadhaar, bank details, driving licence, safety certificates) with **expiry tracking and automatic renewal alerts** to Time Office 30/7 days ahead.
- **Contractor & gang management** — register contractors, attach their gangs, and get contractor-wise attendance/incident rollups. (Sugar mills run heavily on seasonal contractor labour — this is where headcount disputes happen.)
- **Visitor & gate pass module** — front-gate tablet flow: visitor photo (face capture reuses SelfieCamera), host approval push, timed gate pass with QR (QR generation already ships in the app's ID-card feature).
- **Face-enrol at onboarding** — the existing face-enrol flow becomes a mandatory checkpoint of registration approval, so day-one punches are already `Verified+`.

*Builds on:* registration tokens, approval queues, face reference bootstrap, QR ID card, R2 storage.
*Estimated effort:* **3 weeks**.

### 2.3 MD Dashboard Pro *(management-requested)*

The Command Center currently answers *"what is happening now."* Pro makes it answer *"how are we trending, and where is the money going."*

- **Trends & comparisons** — week-vs-week and season-vs-season charts for attendance %, lateness, complaint volume/closure time, per department.
- **Manpower analytics** — daily strength vs. sanctioned strength per department; overtime indicators; contractor vs. permanent split (from Registration Suite).
- **One-click exports** — Excel/CSV export of any register (attendance muster, complaint log, approvals) for auditors and the board.
- **Control-room TV mode** — full-screen auto-rotating dashboard (complaint feed → dept KPIs → safety board) for a wall display in the MD/CGM office.
- **Scheduled digests** — the nightly PDF (already live) gains a WhatsApp/SMS-friendly morning summary and a weekly management review pack.
- **Drill-to-person** — click any number and reach the underlying rows, down to the individual punch or complaint.

*Builds on:* dashboard aggregates + caching layer, fpdf2 report engine, incidents feed.
*Estimated effort:* **3 weeks** (parallel with 2.2).

### 2.4 Post-launch hardening track *(engineering, runs alongside)*

Committed fixes from the launch backlog — invisible to users, essential for scale:

| Item | Why |
|---|---|
| Mobile Approvals → Attendance **Reject button** restore | Managers can currently only approve flagged rows from mobile |
| Shift-swap concurrency guard (`SELECT … FOR UPDATE`) | Prevents double-approval race during peak swap season |
| Offline outbox idempotency (client UUID + server dedup) | Eliminates rare duplicate complaints on flaky networks |
| Full-decode upload validation | Rejects corrupt media at upload, not at view time |
| Ops guardrails (`.dockerignore` for destructive scripts, `GET /admin/employees/{id}`) | Safer production operations |

*Estimated effort:* **1.5 weeks**, first in the queue the moment the code freeze lifts.

**Phase 1 total: ~6 weeks.**

---

## 3. Phase 2 — Safety & Control (Weeks 7–16)

> Goal: make Prasad Sugar demonstrably the safest mill in the district — with evidence a factory inspector can be shown on a screen.

### 3.1 Safety Eyes *(management-requested — flagship)*

Safety Eyes turns every phone (and later, fixed cameras) into a safety sensor. It is the natural extension of the eye in the HogoPlus logo.

**Module A — Hazard watch (mobile-first)**
- **One-tap hazard report** — a yellow sibling of the red complaint tile: photo → AI classifies the hazard type (spill, missing guard, blocked exit, unsafe scaffolding) using the same vision pipeline that powers ANPR/gauge reading.
- **PPE spot-check AI** — supervisor photographs a work crew; AI flags missing helmets/vests and logs a scored PPE compliance entry per department.
- **Near-miss log** — voice-note-first reporting (semi-literate friendly, reuses the voice pipeline) with anonymity option, so workers actually report.

**Module B — Zone safety (beacon-powered)**
- **Restricted zone alerts** — the 6 live BLE beacons (and future ones) define danger zones (boiler, centrifugal, mill house). A worker's phone entering a zone they're not rostered for raises a silent alert to Security and the HOD.
- **Zone occupancy board** — live "who is in which zone" panel on the webdash, from the same beacon telemetry the attendance ladder already collects.

**Module C — Emergency muster & roll-call** *(our recommendation — highest life-safety value)*
- One button on the CGM/MD dashboard: **MUSTER**. Every phone receives a full-screen trilingual alarm; workers tap "I am safe" at the assembly point (GPS + beacon verified).
- Live roll-call board: green = safe, amber = not responded, red = last seen in an affected zone — computed from today's punches + last beacon sighting.
- Post-drill PDF report auto-generated (reuses the report engine) — inspector-ready evidence of drill compliance.

**Module D — Safety scoreboard**
- Department safety scores (hazards closed on time, PPE compliance, near-miss reporting rate — reporting *raises* the score), displayed on Dept Home Screens and TV mode. Gamified, monthly "safest department" recognition.

*Builds on:* incidents engine, AI vision, BLE beacons, push notifications, report engine.
*Estimated effort:* **5 weeks** (A+D: 2, B: 1.5, C: 1.5).

### 3.2 Digital Permit-to-Work *(our recommendation)*

Hot work, confined-space entry, electrical isolation — today these live on paper. Digital permits are the single biggest audit-readiness upgrade available:

- Requestor raises a permit from the forms engine (checklists, photos of isolation, gas-test values via **gauge-read AI**).
- Multi-signature approval chain (HOD → Safety → issuer) with face-verified sign-off.
- Active permits visible on the zone occupancy board — Safety Eyes knows *why* someone is in the boiler zone.
- Auto-expiry with escalation if not closed out.

*Builds on:* forms engine, approval chains, face verification, beacon zones.
*Estimated effort:* **3 weeks**.

### 3.3 Kiosk Attendance *(our recommendation)*

Not every worker has a smartphone. A ₹15k Android tablet at each gate becomes a face-recognition punch station:

- Worker taps their emp-id or scans their QR ID card (already in the app) → camera captures → the **existing Rekognition pipeline** verifies against their enrolled reference → punch recorded with the same ladder semantics.
- Fully offline-tolerant (outbox pattern already proven).

*Builds on:* face verification, attendance API, QR ID cards.
*Estimated effort:* **2 weeks**.

**Phase 2 total: ~10 weeks.**

---

## 4. Phase 3 — The Intelligent Mill (Weeks 17+)

> Goal: use the data HogoPlus is already collecting to run the season better than any competitor's spreadsheet ever could.

### 4.1 Cane Yard Logistics Pro *(our recommendation — highest ROI for a sugar mill)*

Crushing season lives and dies at the weighbridge. The ANPR engine already reads plates in production (proven: MH02FX2660 detected live). Extend it:

- **Gate-in by camera** — security photographs the truck; ANPR logs plate, timestamp, and queue token automatically; farmer/transporter linked from a registry.
- **Weighbridge slip capture** — photo of the slip → AI text extraction (same DetectText pipeline) → gross/tare/net auto-logged, mismatch alerts.
- **Yard queue board** — live truck queue on the webdash and a TV at the yard; SMS to the transporter when their token is called.
- **Season analytics** — daily crush-supply correlation, transporter turnaround times, plate-wise trip history (plate search already exists).

*Estimated effort:* **4–5 weeks**.

### 4.2 Predictive Maintenance Assistant

Every breakdown complaint since launch is a labelled data point (machine, department, severity, photos, resolution time).

- LLM-generated **recurring failure digests**: "Mill House pump #2 — 4th bearing failure this season; average downtime 6.2 hours."
- Maintenance calendar with checklist forms; overdue tasks escalate through the existing ladder.
- Gauge-read AI trends: out-of-range readings plotted over time per instrument, warning before failure.

*Estimated effort:* **3 weeks**.

### 4.3 Payroll-Ready Attendance & Leave

- Leave application/approval workflow (forms engine) with balances.
- **Factories Act muster roll** exports (Form 12-compatible) directly from verified attendance — no re-typing into payroll.
- Overtime computation rules per shift; contractor-wise billing statements (pairs with Registration Suite).

*Estimated effort:* **3–4 weeks**.

### 4.4 Sahayak 2.0 — Voice-First Factory Assistant

- **Speak, don't type**: hold-to-talk Marathi questions (Whisper pipeline already integrated), spoken answers back (TTS).
- Personal queries: "माझी हजेरी दाखवा" → the assistant answers from the user's own attendance/leave data, not just SOPs.
- Manager queries: "आज कोण गैरहजर आहे?" → grounded, scoped, cited answers from live dashboard data.
- Onboarding tutor: walks a new joinee through their first punch, first complaint, first form — in their language.

*Estimated effort:* **3 weeks**.

**Phase 3 total: ~13–15 weeks (modules selectable independently).**

---

## 5. Roadmap at a Glance

| Phase | Window | Modules | Headline outcome |
|---|---|---|---|
| **1 — Consolidate & Delight** | Weeks 1–6 | Dept Home Screens · Registration Suite · MD Dashboard Pro · Hardening pack | The app every department calls "ours"; management gets trends + exports |
| **2 — Safety & Control** | Weeks 7–16 | Safety Eyes (hazards, PPE AI, zones, muster) · Permit-to-Work · Kiosk attendance | Inspector-ready safety evidence; zero-smartphone workers covered |
| **3 — The Intelligent Mill** | Weeks 17+ | Cane Yard Logistics Pro · Predictive Maintenance · Payroll-ready attendance · Sahayak 2.0 | Season logistics, prediction, and payroll all on one platform |

Modules within a phase can be re-sequenced; effort figures assume the current single delivery team and include testing on real devices at the plant.

---

## 6. Why HogoPlus wins against competing apps

1. **The hard infrastructure is already paid for.** Beacons are installed and matched in production; face references are enrolled; ANPR reads real plates; the RAG stack answers in Marathi. Competitors quote months just to reach today's baseline.
2. **Built for this workforce.** Marathi-first, voice-first, 3-tap flows for semi-literate users — proven in the field, not promised in a slide.
3. **One platform, one login, one data model.** Every module above shares the same employee record, the same approval engine, the same audit trail — no integration projects, no data silos.
4. **Evidence, not claims.** Watermarked photos, face-verified punches, beacon-verified zones, immutable audit events — every register in this proposal is defensible in an audit or a labour dispute.
5. **Scales with the mill.** The architecture (managed Postgres, R2 media, in-process AI, load-tested to 300 concurrent users with zero 5xx) is already sized for the 5,000-employee target.

---

## 7. Immediate next steps

1. Management selects/reorders Phase 1 modules (we recommend starting all four tracks in parallel as scoped).
2. Code freeze lifts after the v1.0.14 launch is declared stable → hardening pack (§2.4) ships first.
3. Detailed sprint plan + acceptance criteria delivered for each approved module before its build starts.

*— End of proposal —*

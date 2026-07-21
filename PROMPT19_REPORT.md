# HOGOPLUS-FS — PROMPT 19 LAUNCH-EVE ADVERSARIAL / CHAOS / SECURITY / SCALE REPORT

Date: 2026-06 (launch eve) · Mobile APK v1.0.6 **FROZEN** (untouched) · Backend/webdash only.

## 1. SEVERITY-RANKED FINDINGS MATRIX

| # | Severity | Area | Finding | Status |
|---|----------|------|---------|--------|
| 1 | **MINOR** (fixed) | B7 Security | `GET /incidents?status=<garbage>` and `GET /submissions?status=<garbage>` passed an invalid value straight to a Postgres ENUM column → unhandled **500** (worker-triggerable). Not SQL injection (queries are parametrized). | **FIXED tonight** — validate against allowed enum values → **422**. Regression tests added (`test_prompt19.py`). |
| 2 | MINOR | A4 Concurrency | Self-registration `emp_id = max+1` has no `IntegrityError` catch → two simultaneous registrations could raise 500 instead of a clean retry. | **v1.0.8** (registration is CLOSED for launch → not reachable). |
| 3 | MINOR | A3 Concurrency | Concurrent shift-swap `decide(approve)` relies on status-guard, not a row lock; a true simultaneous double-approve could hit the `uq_shift_assignment` constraint → 500 instead of 409. Not reproduced live (guard held: exactly 1 success). | **v1.0.8** (add `SELECT … FOR UPDATE` on swap decide). |
| 4 | MINOR | E Scale / DB | `incidents.reported_by` and `incidents.created_at` are unindexed (hot path `/incidents/mine`). Negligible at current volume (~96 rows). | **v1.0.8** index. |
| 5 | MINOR | C Data | `date_from`/`date_to`/`date` query params use `datetime.fromisoformat` without try/except → malformed date → 500 on a few manager endpoints. | **v1.0.8** (mirror the status-guard pattern). |
| — | — | — | **No CRITICAL or MAJOR launch-blockers found.** | — |

## 2. FIXED TONIGHT vs v1.0.8

**Fixed tonight (backend, low-risk):**
- Enum status-filter 500 → 422 in `routers/incidents.py` and `routers/forms.py`.
- Added `tests/test_prompt19.py` (3 regressions). Pytest: **183 → 186, all green.**

**v1.0.8 backlog:** findings #2–#5 above, plus the pre-existing mobile idempotency item
(optimistic-retry duplicate incidents) — all deferred, mobile frozen.

## 3. PART-BY-PART RESULTS

### Part A — Concurrency (all PASS)
- **Double punch-in:** 12 concurrent punches → exactly 1 row (unique `uq_attendance_emp_date` + IntegrityError→409). No duplicates, no 5xx.
- **Concurrent incident status:** 10 concurrent updates → no 5xx, consistent state.
- **Concurrent shift-swap decide:** 8 concurrent approvals → exactly 1 success (200), rest 409, no 5xx.
- **OTP flood:** 15 rapid sends on demo account (short-circuit, no SMS) and 15 on unknown number (all 403, registration closed) → no 5xx, no SMS credits burned.

### Part B — Security / Auth (all PASS)
- **IDOR** (worker reads another's incident) → 403/404.
- **Vertical priv-esc** (worker → dashboard/flagged/pending/escalation-targets/status-change) → 403.
- **Mass-assignment** (PATCH /employees/me with role_code=MD, is_demo, emp_id, onboarding_status) → ignored; role/emp_id unchanged.
- **JWT**: wrong-secret → 401; `alg=none` → rejected; expired → 401; registration-token-as-access (type confusion) → 401.
- **Demo↔real boundary**: demo user reading a REAL incident → 404. Confirmed isolation.
- **Injection**: SQLi payloads parametrized (no injection); invalid enum → 422 (post-fix); bad month → 400.
- **File-upload abuse**: `.exe` → 400, bad-magic jpg → 400, empty → 400, path traversal (`../etc/passwd`) → 404.
- **ALLOW_NEW_REGISTRATION=false**: unknown-number OTP → 403 `registration_closed`; register w/ bad token → 401.

### Part C — Data Integrity (all PASS)
- Haversine accuracy (~1000m for 0.009° lat, 0m self); geofence inside(77m)/outside(3.9km) decision correct.
- Cross-midnight C-shift (00:00 start): 01:10 → late, 00:10 → on-time (15-min grace). Attribution uses IST calendar date.
- Timezone: IST offset = +5:30; UTC-stored punch → IST-date attribution consistent.
- Escalation window = 48h exactly.

### Part D — Resilience / Chaos (all PASS)
- **Scheduler double-run guard**: Redis `NX` lock → 1st acquire True, 2nd False (single execution across containers).
- **Redis outage during job**: `_run` fails open — job still executes when lock check throws.
- **R2 / LLM / Rekognition / backup failures**: background tasks wrapped in try/except + `logger.exception` (fail-open; never block the request path).
- **SMS**: `SMSDeliveryError → 502`, `NotConfigured → 503` (surfaced, not silent).

### Part E — Scale (INDICATIVE — see caveat)
Staged pod-local load (demo accounts, read-heavy + bounded writes, single reused media key):

| VU | rps | p50 ms | p95 ms | p99 ms | err% (5xx+exc) | backend RSS |
|----|-----|--------|--------|--------|----------------|-------------|
| 20 | 6 | 915 | 4572 | 6645 | 0.00% | 26 MB |
| 300 | 21 | 901 | 4646 | 6782 | 0.00% | 26 MB |
| 500 | 22 | 856 | 4343 | 6193 | 0.00% | 26 MB |

- **Zero 5xx, zero exceptions, zero "500 Internal" in logs at 500 VU. RSS flat at 26 MB.**
- Latency is **identical across 20→500 VU** → it is a fixed floor, not contention. Root cause: this pod is **~425ms cross-region RTT from Neon DB** (documented in `database.py`), and each request does several DB round-trips. Throughput is RTT-gated, not CPU/memory/pool gated.
- Connection pool (size 40 + overflow 110, timeout 45s) absorbed 500 concurrent VUs with **no exhaustion or timeouts**.
- **CAVEAT (per instruction):** pod-local numbers are **INDICATIVE, not identical to the deployed 1Gi container**. Production runs co-located with Neon (ap-south-1) at a fraction of this RTT, and without `--reload`, so real throughput will be materially higher and p95 far lower. **No error/memory ceiling was reached at 500 VU** — the app degrades gracefully (latency only), it does not break.

### Part F — Localization (PASS)
- Webdash i18n: **141 keys, 0 empty Marathi values, 120 `t()` keys all defined → no runtime-missing keys.** Trilingual `[en,hi,mr]` tuple type structurally enforces parity.
- Marathi layout overflow: strings present; recommend a quick visual pass on the webdash (not a blocker). Mobile Marathi is frozen.

## 4. DEMO / REAL ISOLATION CONFIRMATION
Baseline real (is_demo=false) **before**: employees 403 · incidents 35 · attendance 8 · form_submissions 1 · notifications 90.
**After the entire A+B+E assault**: **403 · 35 · 8 · 1 · 90 — UNCHANGED.** Every test write stayed inside the demo bubble (demo counts churned + auto-cleanup ran). Isolation intact.

## 5. PYTEST
**186 passed** (was 183; +3 new Prompt-19 regressions). Suite green after every fix.

## 6. GO / NO-GO
**GO ✅** — No critical or major launch-blockers. The one worker-triggerable 500 (enum filter) is fixed and regression-tested. Auth, IDOR, demo/real isolation, concurrency guards, chaos fail-open paths, and file-upload defenses all hold. System sustained 500 VU with zero errors and flat memory; scale is DB-RTT-gated and will improve in production. **Do NOT auto-deploy** (per instruction) — this is a readiness verdict for manual launch.

### Launch-day mitigations for deferred (frozen-mobile) items
- **Duplicate-incident risk (mobile outbox retry, v1.0.8):** on-site, if a worker's incident appears twice, managers can resolve/ignore the duplicate from the webdash — no data corruption, both rows are valid & independently actionable. **Watch-this** note for you on-site.
- **Registration collision (#2):** N/A at launch — registration is CLOSED (`ALLOW_NEW_REGISTRATION=false`); Time Office onboards manually.
- **Shift-swap double-approve (#3):** extremely low probability (two managers approving the same swap in the same ~400ms); if it 500s, a simple retry succeeds and no bad state is written. Backend guard already prevents duplicate swap application via the unique constraint.

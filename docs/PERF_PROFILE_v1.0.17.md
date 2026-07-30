# Performance Profile — v1.0.17 (measured 2026-06)

**Scope:** measured profiling report only (per your instruction, fixes ride v1.0.19).
No behaviour was changed for this report.

---

## 1. Headline finding — it's not bandwidth, it's round trips

Measured from the backend host:

| Probe | Cost |
|---|---|
| PostgreSQL (Neon, ap-southeast-1) `SELECT 1` | **217 ms per query** |
| Redis (Upstash) `PING` | **215 ms per op** |
| New DB connection (TLS handshake) | 1,339 ms |

The backend runs in a different region from the database and Redis. **Every DB query
and every Redis call pays ~220 ms of pure network latency.** A typical authenticated
API request does 3–6 sequential round trips (token check → employee fetch → role load
→ domain query → maybe Redis), so the *floor* for any API call is ~0.7–1.3 s —
regardless of the user's 200 Mbps connection. This is why the app feels sluggish even
on fast Wi-Fi and will feel identical (not worse) on mobile data for small payloads.

> Action with the biggest single gain and **zero code risk**: co-locate the backend
> with the DB region (or vice-versa). This alone cuts every API call by 60–85%.
> Please confirm which region api.hogoplus.in runs in — if it's already next to
> Neon ap-southeast-1, production numbers will be much better than the table below
> and the remaining items are the real targets.

## 2. Measured API latency (CGM account, warm server, 3 samples)

| Endpoint | Payload | p50 | Max | Verdict |
|---|---|---|---|---|
| GET /api/incidents | 2.3 KB | **2,727 ms** | 2,727 ms | 🔴 worst — ~12 round trips, no LIMIT |
| GET /api/admin/employees/pending | 2 B | **1,847 ms** | 3,185 ms | 🔴 2 full-table max()/regex scans for emp-id suggestion |
| GET /api/attendance/beacon-registry | 5.4 KB | 1,646 ms | 1,653 ms | 🟡 already mitigated: 10-min client cache (v1.0.17) |
| GET /api/auth/me | 0.6 KB | 971 ms | 1,074 ms | 🟡 3–4 round trips |
| GET /api/departments | 2.2 KB | 988 ms | 994 ms | 🟡 cacheable, rarely changes |
| GET /api/dashboard/summary | 1.4 KB | **123 ms** | 133 ms | 🟢 proves the stack CAN be fast (few round trips) |

Payloads are all tiny (≤5.4 KB) → **oversized payloads are NOT a cause today.**
The 20× spread between /dashboard/summary (123 ms) and /incidents (2.7 s) is purely
the number of sequential DB round trips per request.

## 3. App bundle & cold start

- Production JS bundle: **5.66 MB, 3,906 modules** (Hermes bytecode on EAS; parse is
  fast but module init runs at every cold start). Assets: 2.0 MB.
- Cold start gate: splash is held until 4 Baloo2 fonts + icon fonts register, then
  auth hydration does ~6 sequential SecureStore/AsyncStorage reads before first render.
  Estimated 300–600 ms of avoidable serial storage I/O.
- Home screen data loading is already parallel (4–6 `useCachedFetch` hooks with cache) 🟢.

## 4. Media pipeline

| Item | Current | Assessment |
|---|---|---|
| Incident photo | camera quality 0.85 + watermark burn-in compress | 🟢 ~1–2 MB, fine |
| Face enroll selfie | resize + compress 0.7 | 🟢 |
| Incident video | **720p, 30 s cap, no bitrate cap** → typical 15–25 MB (40 MB server cap) | 🔴 dominant upload on mobile data (30–90 s on 4G) |
| Punch flow | GPS ∥ upload ∥ BLE ∥ geocode already parallel (v1.0.17) | 🟢 |

## 5. Prioritised fix list (proposed for v1.0.19)

| # | Fix | Type | Expected gain |
|---|---|---|---|
| 1 | Co-locate backend & DB region (deployment setting, no code) | Infra | Every API call −60–85% (e.g. /incidents 2.7 s → ~0.6 s) |
| 2 | /incidents: add `LIMIT 50` + pagination; eager-load role in auth dependency | Backend | 2.7 s → <400 ms; stops season-long growth |
| 3 | /admin/employees/pending: compute emp-id suggestion from an indexed query | Backend | 1.8–3.2 s → <300 ms |
| 4 | Video: add `videoBitrate` cap (~2 Mbps) and/or 15 s duration cap | App (v1.0.19 build) | Upload size −50–70% |
| 5 | Cache /departments client-side like beacon-registry (10-min TTL) | App | −1 s on screens that fetch depts |
| 6 | Parallelise auth-hydration storage reads (`Promise.all`) | App | Cold start −300–600 ms |

**Note per your rule:** none of these were applied to v1.0.18. Items 1–3 are
backend/infra-only — they do NOT require an app build and can ship independently
whenever you approve, without re-testing the APK.

## 6. What we still need from the field (your factory visit)

The v1.0.17 punch **timing card** (BLE Diagnostics screen) records the on-device
breakdown (GPS / upload / zone / geocode / total). Please capture 3–5 punches on
mobile data — that tells us how much of the remaining wait is network vs device,
and whether api.hogoplus.in has the same cross-region penalty measured here.

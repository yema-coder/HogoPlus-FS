# DEPLOY ORDER — v1.0.27 (Attendance verification ladder + per-punch location + Mappls maps & geocoding)

## What ships
1. **Attendance verification ladder (backend, flag-gated OFF)** — a no-beacon punch that is inside
   the factory geofence (+grace) with an acceptable GPS accuracy radius AND a passing selfie face
   check is recorded as **verified (by location/`gps`)** instead of flagged. Beacon stays the first
   path (`verified_plus`). Field departments (`Department.geofence_exempt`, e.g. AGRICULTURE) are
   **verified by face-pass + a captured GPS fix** with no beacon / factory-geofence requirement
   (`verification_path='field'`). All thresholds come from **settings**, never hardcoded.
2. **Per-punch + per-incident location persistence (backend)** — every punch stores
   `gps_accuracy`, `geo_distance_m`, `verification_path` (`beacon`|`gps`|`field`|null) and
   `geo_address`; incidents gain `gps_accuracy`. The async face check may still downgrade an already
   stored punch to `flagged(face_mismatch)` — unchanged.
3. **Mappls (MapmyIndia) server-side geocoding + maps (backend)** — reverse geocoding (coords →
   readable Indian address) runs on the backend and is **cached** in the new `geocode_cache` table;
   `GET /api/dashboard/map-static` proxies a still-image PNG (token stays server-side);
   `GET /api/dashboard/maps-token` mints a short-lived token for the **webdash** interactive map only.
   **No Google Maps, no OSM.**
4. **Mobile map preview (flutter of incidents/attendance, client)** — `MapPreview` now fetches the
   authenticated `/map-static` PNG through the API client (so the Mappls token never reaches the
   device) and falls back to raw coordinates + an **Open in Maps (Mappls web)** button on any
   failure. Incident detail shows an Object-vs-Device location block with `±N m` accuracy + the map.
5. **Auto punch-out (backend scheduler, flag-gated OFF)** — when enabled, writes a punch-out at
   shift-end + grace, marked `punch_out_source='auto'` (surfaced for review, never a silent full day).

Mobile credentials: the app has **zero** Mappls references — it only calls the authenticated
static-map proxy. Verified: `grep -rn "maps-token\|MAPPLS\|apikey" frontend/{src,app}` → none.

## Rollback point
Unchanged from v1.0.26: in-app APScheduler `run_backup_sync` does a 4-hourly `pg_dump → gzip → R2`
at `backups/YYYY-MM-DD/HHMM.sql.gz` (keep 14). Confirm the newest dump is dated today and a sensible
size BEFORE migrating; else take an RDS console snapshot. Restore with `scripts/restore_latest.py`.

## EC2 deploy order (service = `backend`; auto-migrate OFF → migrations are MANUAL)
```bash
git pull                                              # pull the release branch
docker compose build backend
docker compose run --rm backend alembic current       # expect 0026 (prod)
docker compose run --rm backend alembic upgrade head   # -> 0030 (idempotent, additive-only)
docker compose up -d backend
docker compose logs --tail=20 backend | grep -i "auto-migrate\|revision"
#   expect: "auto-migrate disabled, current revision = 0030 (code head = 0030)"
```
All four new migrations are **additive-only** (new nullable columns + one new table) — no data
migration, safe to apply with the old container still serving.

## Alembic migrations (head = 0030; prod was 0026)
`… 0026 → 0027_photo_plate_original_text → 0028_face_references →`
**`0029_attendance_location_ladder`** → **`0030_mappls_geocode_cache`**
- **0029** adds `settings`: `gps_verify_enabled`, `gps_accuracy_max_m`, `geofence_grace_m`,
  `auto_punch_out_enabled`, `auto_punch_out_grace_min`; and `attendance`: `gps_accuracy`,
  `geo_distance_m`, `verification_path`, `geo_address`, `punch_out_source`.
- **0030** adds the `geocode_cache` table (unique on `lat_key,lng_key`) and `incidents.gps_accuracy`.

## Flags / settings (ALL new feature flags default OFF/FALSE — legacy behaviour preserved)
Edit at runtime with `PATCH /api/admin/settings {...}` (CGM/MD token) or the webdash Admin → geofence
card. No rebuild required.
| setting | default | meaning |
|---|---|---|
| `gps_verify_enabled` | **false** | GPS as a valid 2nd verification path (beacon stays 1st) |
| `gps_accuracy_max_m` | `100` | reject a GPS fix worse than this accuracy radius (m) on the GPS path |
| `geofence_grace_m` | `150` | tolerance added to `radius_meters` when deciding "inside" on the GPS path |
| `auto_punch_out_enabled` | **false** | scheduler writes an AUTO punch-out at shift-end + grace |
| `auto_punch_out_grace_min` | `60` | minutes after shift-end before auto punch-out |
| `face_collection_enabled` | **false** | (unchanged, Part D) reference-face collection; no matching |

## Exact EC2 env vars (add/confirm) — names only, NEVER commit values
```
MAPPLS_CLIENT_ID=...        # NEW — Mappls OAuth client id   (SERVER-SIDE ONLY)
MAPPLS_CLIENT_SECRET=...    # NEW — Mappls OAuth client secret(SERVER-SIDE ONLY)
# everything else unchanged from current prod .env:
DISABLE_AUTO_MIGRATE=true   # REQUIRED in production (manual migrations only)
OTP_MODE=smsgatewayhub · FILE_STORAGE_MODE=s3 · DATABASE_URL · REDIS_URL · JWT_SECRET
AWS_* / S3_* · EMERGENT_LLM_KEY · OPENAI_API_KEY · SMSGATEWAYHUB_* / OTP_TEMPLATE_TEXT
```
If `MAPPLS_CLIENT_ID/SECRET` are absent, geocoding + maps **fail gracefully** (UI shows coords +
Open-in-Maps); nothing blocks a punch or incident.

## Mappls usage estimate (3 factories)
Reverse geocoding is cached on an **~11 m grid** (`geocode_cache`), and field staff punch repeatedly
in the same cells, so **billed reverse-geocode calls ≈ distinct ~11 m cells/day**, not punch count.
- **Launch (~400 punches/day, 3 factories):** office/plant punches cluster at a handful of
  gates/zones → tens of distinct cells. Worst case (no cache benefit, all unique cells) = 400/day;
  realistic steady state ≈ **30–80 reverse-geocode calls/day** + a handful of incident geocodes.
- **Scaled (~2,200 punches/day):** worst case 2,200/day; realistic ≈ **150–400/day** after the
  cache warms. Static-map PNGs are additionally disk-cached on the device and served with a 1-day
  `Cache-Control`, so a given spot is fetched at most once/day/device.
- Both reverse-geocode and still-image sit comfortably inside a standard Mappls advanced-maps plan
  at these volumes. Monitor the Mappls console; if nearing quota, raise the grid rounding in
  `app/mappls._round_key` (coarser grid = fewer calls).

## Version release / in-app update gate procedure
1. Bump `frontend/app.json` → `expo.version` (`A.B.C`) **and** `expo.android.versionCode`
   (`A*10000 + B*100 + C`; 1.0.27 → 10027) and `ios.buildNumber`.
2. Pre-publish guard (CI/local): `cd frontend && node scripts/check_version.mjs`
   (fails if versionCode ≠ scheme or ≤ last shipped floor in `scripts/.version_floor`, now `10025`).
3. **Publish** the APK/AAB via the Emergent Publish panel (no EAS CLI).
4. After a successful publish: `node scripts/check_version.mjs --commit` (advances `.version_floor`).
5. Tell the in-app update gate what shipped (on the server, admin/MD token):
   `python scripts/set_app_version.py 1.0.27`  (add `--force` for a BLOCKING update, `--notes "..."`,
   `--apk-url ...`). Equivalent HTTP: `PUT /api/admin/app-version {"latest_version":"1.0.27","force_update":false}`.
   The mobile banner (`GET /api/app-version`, checked once/day, dismissible) then offers the update.

## This build
- app.json: version **1.0.27**, android.versionCode **10027**, ios.buildNumber **1.0.14**.
- No new native modules or permissions in this round → the change is JS/asset-only on mobile; a
  standard rebuild ships it. API stays pinned to `https://api.hogoplus.in` in release builds.

## Verification done in sandbox (2026-06, this round)
- Backend full suite **379 passed, 2 skipped** (incl. `tests/test_attendance_ladder.py` 6/6).
- Mappls endpoints live: `/maps-token` → `configured:true`; `/map-static` → HTTP 200 `image/png`
  (400×260, ~65 KB).
- Mobile incident-detail map verified on web preview as Demo CGM D500: Object/Device location blocks,
  `±12 m` accuracy, Mappls static map with pin + `© Mappls`, "See in Map" (Mappls web). No OSM.
- i18n parity GREEN across en/hi/mr for all new map/location strings.
- Migration chain linear 0026→0030, all additive-only.

# DEPLOY ORDER — v1.0.26 (Camera-AI feedback round: Incident detail revamp + AR fixes + model prefetch + auto-migrate safety)

## What ships
1. **Incident Photo Detail revamp (mobile)** — photo now clean/unobstructed; all metadata below
   it; 2-col facts grid; "People detected (N)" clear face-crop strip; "Number plates (N)" list
   (tap-to-edit, rank ≤ 3); full-screen "view with boxes". Trilingual. Backend UNCHANGED.
2. **AR distance fixes (mobile native — Android Kotlin + iOS Swift)** — tap→depth mapping now
   uses ARCore `transformCoordinates2d` / ARKit `displayTransform.inverted()` (was sampling the
   wrong pixel); native emits RAW per-frame samples so the JS filter produces a real ±
   uncertainty and suppresses noisy readings; fixed top distance banner clear of the shutter;
   admin/dev Debug HUD; admin tape-measure calibration (`/ar-calibration`). Backend UNCHANGED.
3. **Model prefetch (backend build)** — `scripts/prefetch_models.py` + a Dockerfile `RUN` bake the
   YOLOv9 plate detector (7.4 MB) + CCT-XS OCR (3.2 MB) ONNX weights into the image so the
   runtime container needs NO HTTP egress. YuNet (0.2 MB) already vendored.
4. **Auto-migrate safety (backend)** — `DISABLE_AUTO_MIGRATE=true` now makes ZERO schema changes
   and logs one line `auto-migrate disabled, current revision = X (code head = Y)`; warns (never
   crashes, never migrates) when the DB is behind. **Production MUST set this flag and apply
   migrations manually.**

## Rollback point WITHOUT an RDS console snapshot (user's choice)
The app itself takes a **4-hourly `pg_dump` → gzip → R2** at `backups/YYYY-MM-DD/HHMM.sql.gz`
(IST), keeps the newest 14, created by the IN-APP APScheduler job `run_backup_sync` (app/tasks.py)
— there is NO OS cron. The prod image ships `postgresql-client-18`, so it is a real schema+data
`pg_dump` (not the Python fallback). Restore with `scripts/restore_latest.py`.

**BEFORE migrating, verify the latest dump is real and from RDS (run on the host):**
```bash
# 1) Confirm the DB the backup dumps is RDS, NOT the legacy Neon (password redacted):
docker compose run --rm backend sh -lc 'echo "$DATABASE_URL" | sed -E "s#//[^@]*@#//***@#"'
#    host MUST end in .rds.amazonaws.com  — if it ends in .neon.tech, STOP.
# 2) List the newest R2 dumps with timestamp + size:
docker compose run --rm backend python - <<'PY'
from app.storage import S3Storage
s=S3Storage(); r=s.client.list_objects_v2(Bucket=s.bucket, Prefix="backups/")
for o in sorted(r.get("Contents",[]), key=lambda x:x["LastModified"])[-6:]:
    print(o["LastModified"].isoformat(), f'{o["Size"]/1024:.0f} KB', o["Key"])
PY
```
PASS if the newest key is dated today (IST, within ~4h) and the size is sensible for a live
factory DB (expect hundreds of KB to several MB gz — a few-KB file = data missing → STOP).
To force a fresh one now: `docker compose run --rm backend python -c "from app.tasks import run_backup_sync; print(run_backup_sync())"`.
If the newest dump is MISSING, OLD, or SUSPICIOUSLY SMALL → STOP and take a console snapshot.

## Pre-build host prep (run on EC2)
```bash
sudo sysctl -w vm.swappiness=10 && echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-hogoplus.conf
#   NOTE: swappiness only matters if a swap device exists; t3.medium has none by default.
docker builder prune -f                                   # reclaim build cache
docker tag hogoplus-backend:latest hogoplus-backend:rollback-20261006   # image rollback point
```

## EC2 deploy order  (service = `backend`; auto-migrate OFF → migrations are MANUAL)
```bash
git pull                                      # pull main FIRST (standing rule)
docker compose build backend                  # prefetch_models.py runs INSIDE the build (bakes ONNX)
# DB is at 0019 → this applies 0020,0021,0022,0023,0024, with the OLD container serving:
docker compose run --rm backend alembic current             # expect 0019
docker compose run --rm backend alembic upgrade head        # -> 0024 (idempotent)
docker compose up -d backend
docker compose logs --tail=20 backend | grep -i "auto-migrate\|revision"
#   expect: "auto-migrate disabled, current revision = 0024 (code head = 0024)"
# Re-run the MANUAL seeds (not run on boot) so this batch's config/allowlist land:
docker compose run --rm backend python scripts/seed_home_configs.py        # CGM/MD "Report incident" tile
docker compose run --rm backend python scripts/seed_ar_debug_allowlist.py  # Amey 0001/8483029039 -> AR debug
# KEEP PLATES OFF (migration default is ON). Face stays ON for smoke test:
#   PATCH /api/admin/settings {"plate_detection_enabled": false}  (CGM/MD token)
```
If step-1 (upgrade) is skipped and the DB is behind, the app still BOOTS and logs a WARNING;
requests touching the new columns/tables fail until you upgrade. It will NOT auto-migrate.

## Alembic migrations (ordered; revision id == filename prefix; head = 0024)
0001_initial_schema · 0002_fix_shift_timings · 0003_phase4_ai_storage · 0004_ux_pack ·
0005_video_password_polish · 0006_ble_mac · 0007_anpr_pipeline · 0008_demo_isolation ·
0009_app_version · 0010_ble_dualmode · 0011_beacon_first_flag · 0012_force_update_flag ·
0013_wave1_dept_upgrade · 0014_reg_context_bilingual_ai · 0015_p1_batch · 0016_nudge_idempotency ·
0017_head_office_md · 0018_live_presence · 0019_presence_phase2 · **0020_broadcasts** ·
**0021_photo_analysis** · **0022_plate_scale** · **0023_broadcast_templates** ·
**0024_ar_debug_allowlist**
> Bold = added during the Broadcast + Camera-AI rounds. If your prod is at **0019**,
> `alembic upgrade head` applies 0020→0024 (verify with `alembic current`). 0024 is a single
> additive column (`settings.ar_debug_emp_ids TEXT NOT NULL DEFAULT ''`) — no data migration.

## requirements.txt
- **No change in this round.** The Camera-AI + Broadcast rounds (already in the repo) need these if
  not already present on your image:
  `opencv-python-headless==5.0.0.93`, `open-image-models==0.6.0`, `fast-plate-ocr==1.1.0`
  (vision), `openpyxl==3.1.5` + `et_xmlfile==2.0.0` (broadcast .xlsx export). `onnxruntime==1.27.0`
  was already added for RAG embeddings.

## Flags / settings (all new feature flags default OFF/FALSE)
- **Backend:** NEW migration **0024** adds `settings.ar_debug_emp_ids` (TEXT, default `''`) — a
  comma/newline allowlist of emp_ids + phones that may see the on-device AR debug HUD/dot with NO
  rebuild. Default empty (nobody). Editable at runtime via `PATCH /api/admin/settings
  {"ar_debug_emp_ids": "..."}` (CGM/MD) and exposed per-user as the computed boolean `ar_debug` on
  `/api/auth/me` + login. Seeded for Amey (0001 / 8483029039) by the seed below.
- ⚠️ Face/plate are gated by `settings.face_detection_enabled` / `plate_detection_enabled`, both
  **server_default TRUE** (added by 0021). So **after you apply the migrations, plate detection
  defaults ON.** Plates stay OFF for this deploy and NO code workaround was added — you MUST turn it
  off at runtime: `PATCH /api/admin/settings {"plate_detection_enabled": false}` (CGM/MD). Face
  stays ON (smoke test ok). `broadcasts_enabled` already defaults FALSE.
- **Env:** **`DISABLE_AUTO_MIGRATE=true`** — production ALWAYS sets this.
- **Mobile AR debug gate (client):** `__DEV__ || is_demo || role.rank ≤ 2 || profile.ar_debug`
  (the last from the server allowlist). Real workers on real accounts match none → never see it.
- **Mobile (client-only):** AR Debug HUD + reprojection dot + `/ar-calibration` gated to
  `__DEV__ || role.rank ≤ 2`.

## docker-compose.yml diff (worker override as a `command:` line — fits 4 GB)
```diff
   backend:
     image: hogoplus-backend:latest
     env_file: .env
+    # 2 vCPU / 4 GB box: ONE uvicorn worker so only one copy of the ONNX models is
+    # resident (+~160 MB). Mirrors the Dockerfile CMD with --workers 1.
+    command: ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001",
+              "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
```

## Exact EC2 env vars (add/confirm)
```
DISABLE_AUTO_MIGRATE=true          # NEW — REQUIRED in production (manual migrations only)
# everything else unchanged from your current prod .env:
OTP_MODE=smsgatewayhub
FILE_STORAGE_MODE=s3
BACKUP_UPLOAD_ENABLED=true         # (leave unset = ON; sandbox-only sets 0)
OPENAI_API_KEY=...                 # dedicated OpenAI billing (voice STT/TTS)
SMSGATEWAYHUB_API_KEY / _SENDER_ID / _DLT_TEMPLATE_ID / OTP_TEMPLATE_TEXT=...
AWS_* / S3_* keys, DATABASE_URL, REDIS_URL, JWT_SECRET=...
```

## Mobile build (APK/IPA 1.0.26 / versionCode 10026 — via Emergent Publish)
- AR native module (`frontend/modules/expo-ar-distance`) changed → a FULL rebuild is required;
  Expo Go/web CANNOT exercise ARCore/ARKit. API stays pinned to https://api.hogoplus.in in
  release builds (existing src/api/client.ts guard). No new permissions/manifest changes.

## Verification done in sandbox (2026-06, this round)
- Part B: testing_agent iteration_31 — all acceptance criteria PASS, 0 bugs.
- Face pipeline E2E: single-face PD portrait → 1 face @0.917; 4-face crew photo → 4/4
  @0.871–0.914 (no false positives); crops verified correct; threshold score≥0.6.
- Perf (2 vCPU emulated via `taskset -c 0,1`, OMP=2): RSS boot 106 MB → +face 200 → +plate 265 →
  steady 299 (peak 367); full 12 MP photo ~189 ms warm (cold ~310 ms incl. load).
- prefetch_models.py: bakes YuNet 0.2 + YOLOv9 7.4 + CCT-XS 3.2 MB; exits non-zero if any missing.
- DISABLE_AUTO_MIGRATE=true path verified: logs `current revision = 0023 (code head = 0023)`.

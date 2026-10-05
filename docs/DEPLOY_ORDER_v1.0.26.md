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

## EC2 deploy order  (auto-migrate is OFF in prod → migrations are MANUAL)
```bash
# 0. TAKE AN RDS SNAPSHOT FIRST (you already do this).
git pull                                   # pull main FIRST (standing rule)
docker compose build api                   # prefetch_models.py runs INSIDE the build (bakes ONNX)
# 1. Apply schema migrations MANUALLY, with the OLD container still serving:
docker compose run --rm api alembic current             # see where the DB is
docker compose run --rm api alembic history | head -30  # review the chain
docker compose run --rm api alembic upgrade head        # -> 0023 (idempotent)
# 2. Cut over:
docker compose up -d api
docker compose logs --tail=20 api | grep -i "auto-migrate\|revision"
#   expect: "auto-migrate disabled, current revision = 0023 (code head = 0023)"
```
If step-1 is skipped and the DB is behind, the app still BOOTS and logs a WARNING; requests that
touch the new columns/tables fail until you run `alembic upgrade head`. It will NOT auto-migrate.

## Alembic migrations (ordered; revision id == filename prefix; head = 0023)
0001_initial_schema · 0002_fix_shift_timings · 0003_phase4_ai_storage · 0004_ux_pack ·
0005_video_password_polish · 0006_ble_mac · 0007_anpr_pipeline · 0008_demo_isolation ·
0009_app_version · 0010_ble_dualmode · 0011_beacon_first_flag · 0012_force_update_flag ·
0013_wave1_dept_upgrade · 0014_reg_context_bilingual_ai · 0015_p1_batch · 0016_nudge_idempotency ·
0017_head_office_md · 0018_live_presence · 0019_presence_phase2 · **0020_broadcasts** ·
**0021_photo_analysis** · **0022_plate_scale** · **0023_broadcast_templates**
> Bold = added during the Broadcast + Camera-AI rounds. If your prod last deployed at v1.0.25 it
> is at **0018**, so `alembic upgrade head` will apply 0019→0023 (verify with `alembic current`).

## requirements.txt
- **No change in this round.** The Camera-AI + Broadcast rounds (already in the repo) need these if
  not already present on your image:
  `opencv-python-headless==5.0.0.93`, `open-image-models==0.6.0`, `fast-plate-ocr==1.1.0`
  (vision), `openpyxl==3.1.5` + `et_xmlfile==2.0.0` (broadcast .xlsx export). `onnxruntime==1.27.0`
  was already added for RAG embeddings.

## Flags / settings (all new feature flags default OFF/FALSE)
- **Backend:** no new settings flags this round. Face/plate pipelines are gated by the EXISTING DB
  flags `settings.face_detection_enabled` / `settings.plate_detection_enabled` (default ON).
- **Env:** **`DISABLE_AUTO_MIGRATE=true`** — NEW; production ALWAYS sets this. Unset/false = legacy
  auto-migrate behaviour (sandbox only).
- **Mobile (client-only, no backend flag):** AR Debug HUD + `/ar-calibration` are gated to
  `__DEV__ || role.rank ≤ 2` (admins/dev). Normal workers never see them. Calibration scale is
  stored per-device in AsyncStorage (`hogo.ar.calib`), default ×1.000 (no correction).

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

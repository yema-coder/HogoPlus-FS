# DEPLOY ORDER — v1.0.23 batch (nav fixes + approvals All view + MD handover)

## What ships where
| Piece | Half | Goes live |
|---|---|---|
| MD accounts + temp password (seed script) | backend/data | NOW — deploy step 3 |
| Webdash MD identity "Prasad Sugar Mill" | webdash (served by api) | NOW — with git pull + rebuild |
| Back buttons everywhere + hardware-back parity | app | next APK (1.0.23) |
| Approvals "All" stacked view | app | next APK (1.0.23) |

## 1. Deploy backend + webdash
```bash
cd ~/hogoplus && git pull
docker compose build api && docker compose up -d
docker compose exec -T api alembic upgrade head   # no new migrations this batch — must print "head"
```

## 2. Rebuild webdash bundle (if your pipeline doesn't bake it into the api image)
The repo already contains the built bundle (webdash_dist) — git pull is enough.

## 3. MD handover (data, idempotent, audited)
```bash
docker compose exec -T api python scripts/seed_md_handover.py
```
Expect: 0428 (+919096171949) and 1220 (+919561722986) → role=MD,
must_change_password=True; owner 0001 row printed UNTOUCHED.
Temp password for BOTH: `Hogo@123` (emp-id + password on the webdash Password tab).
First login forces a password change. OTP login on the numbers works as usual and
lands on the MD dashboard. Re-running never resets a password they have changed.

## 4. Verify (2 min)
- Webdash → login 0428 / Hogo@123 → forced "Set a new password" → after change,
  sidebar identity reads **Prasad Sugar Mill** (no name, no role label)
- Your own 0001 login unchanged (name shows as before)
- Audit log: `action=employee.md_handover`, 2 rows, source=seed_md_handover.py

## 5. Cut APK 1.0.23 (contains back buttons + All view)
Artifact autopsy greps (release bundle):
```bash
unzip -p app-release.apk assets/index.android.bundle 2>/dev/null | strings > bundle.txt   # or the equivalent for your artifact
grep -c "screen-header-back-button" bundle.txt   # ≥ 1
grep -c "all-section-"              bundle.txt   # ≥ 1 (All view sections)
grep -c "1.0.23"                    bundle.txt   # version string baked
grep -c "api.hogoplus.in"           bundle.txt   # prod API pinned (launch guard)
```

## FINAL THREE (standing rule — every deploy)
1. `docker compose exec -T api python scripts/flag_audit.py` — one-screen truth
2. Admin → Feature flags: verify/flip what this batch needs (no new flags this batch)
3. Admin → App version: bump to 1.0.23 AFTER the APK is distributed (force stays OFF
   until distribution covers everyone — the Admin card now warns about exactly this)

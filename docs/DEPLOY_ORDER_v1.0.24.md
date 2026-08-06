# DEPLOY ORDER — v1.0.24 batch (HEAD OFFICE dept + Add-Employee Wizard + MD Access Redesign)

## What ships where
| Piece | Half | Goes live |
|---|---|---|
| Migration 0017 (dept policy flags + settings MD columns) | backend/data | NOW — step 2 |
| HEAD_OFFICE + Mahesh Makne + shared MD + demotions (seed) | backend/data | NOW — step 3 |
| /auth/md-login, /auth/md-elevate, /admin/md-password, availability API | backend | NOW — step 1 |
| Webdash: password-only MD login tab + Add-Employee Wizard + MD-password card | webdash (served by api) | NOW — step 1 |
| Mobile: Add-Employee Wizard + "Add employee" home tile for HO manager | app | next APK (1.0.24 / versionCode 10024) |

## 0. Before you start
`scripts/seed_head_office_md.py` — the EDIT block at the top is already set:
```python
HO_MANAGER_NAME = "Mahesh Makne"          # real name (confirmed)
HO_MANAGER_EMP_ID = None                  # None = auto-pick next free 4-digit id
```
Override at run time without editing: `--name "Other Name"`.
NOTE: `scripts/seed_md_handover.py` was DELETED (superseded — this batch demotes those two numbers).

## 1. Deploy backend + webdash
```bash
cd ~/hogoplus && git pull
docker compose build api && docker compose up -d
```

## 2. Migration (adds columns only — no data rewrite, safe live)
```bash
docker compose exec -T api alembic upgrade head    # must print: Running upgrade 0016 -> 0017
docker compose exec -T api alembic current         # must print: 0017 (head)
```

## 3. Seed (idempotent, audited — prints the final state itself)
```bash
docker compose exec -T api python scripts/seed_head_office_md.py
```
Expected output ends with:
```
=== FINAL MD-ACCESS STATE ===
  MD password set: YES
  MD OTP numbers:  +919511738318,+918483029039
  Shared account:  MD | Prasad Sugar Mill | role=MD | phone=None | personal_password=none
  HO manager:      <emp_id> | Mahesh Makne | +919511738318 | role=Manager | dept=HEAD_OFFICE
  Demoted rows:
    0428 | Pathan Irfan Husen | +919096171949 | role=Manager | password=none
    1220 | Husen Pathan | +919561722986 | role=Manager | password=none
  HEAD_OFFICE: beacon_exempt=True geofence_exempt=True can_add_employees=True
```
Re-running is safe: it never resets a CHANGED MD password ("MD password already set — NOT touched").

## 4. Verification queries (psql against the prod DB URL)
```sql
-- dept policy flags
SELECT code, beacon_exempt, geofence_exempt, can_add_employees
FROM departments WHERE code IN ('HEAD_OFFICE','TIME_OFFICE');

-- the four accounts in one look
SELECT emp_id, full_name, phone, role_code, department_code,
       (password_hash IS NOT NULL) AS has_personal_password
FROM employees
WHERE emp_id = 'MD' OR phone IN ('+919511738318','+919096171949','+919561722986');

-- MD settings landed
SELECT (md_password_hash IS NOT NULL) AS md_password_set, md_otp_phones FROM settings;

-- audit trail of the batch
SELECT action, count(*) FROM audit_events
WHERE action IN ('employee.created','employee.md_access_revoked','admin.md_password_changed')
  AND detail_json->>'source' IS NOT NULL
GROUP BY action;
```

## 5. Live smoke (2 min, webdash)
- Login page → "MD login" tab → password `Hogo@123` ALONE (no emp_id) → sidebar identity
  **Prasad Sugar Mill**. 5 wrong passwords from one IP → locked 15 min (audited).
- OTP tab → +918483029039 (or +919511738318 once Mahesh is onboarded) → lands on MD dashboard
  (silent md-elevate). Any other manager number → their own dashboard, NO MD access.
- Old numbers +919096171949 / +919561722986: password tab dead, OTP lands as Manager.
- Employees → "+ Add employee" → 5-step wizard; enter an existing phone at step 4 → blocked
  naming the holder.
- Admin (MD only) → "MD dashboard password" card → rotate password away from Hogo@123.

## 6. Cut APK 1.0.24 (wizard + HO-manager home tile)
Artifact autopsy greps (release bundle):
```bash
unzip -p app-release.apk assets/index.android.bundle 2>/dev/null | strings > bundle.txt
grep -c "home-tile-add-employee" bundle.txt   # ≥ 1 (HO manager tile)
grep -c "wiz-empid"              bundle.txt   # ≥ 1 (wizard steps)
grep -c "1.0.24"                 bundle.txt   # version string baked
grep -c "api.hogoplus.in"        bundle.txt   # prod API pinned (launch guard)
```

## FINAL THREE (standing rule — every deploy)
1. `docker compose exec -T api python scripts/flag_audit.py` — one-screen truth
2. Admin → Feature flags: nothing new to flip this batch (dept flags live on the dept rows)
3. Admin → App version: bump to 1.0.24 AFTER the APK is distributed (force stays OFF
   until distribution covers everyone)

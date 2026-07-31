# FLAG AUDIT — one-screen truth of every toggle in the system

## How to get the live truth on production (read-only, zero risk)

```bash
cd ~/hogoplus && docker compose exec -T api python scripts/flag_audit.py
```

Prints one screen: DB feature flags, app-version row, env toggles as the running
API actually loaded them, and which credentials are present (values hidden).
Fallback if the container is down — DB flags only, from any psql:

```sql
SELECT beacon_first_mode, home_config_enabled, vehicle_log_enabled,
       notif_batching_enabled, dup_window_minutes FROM settings;
SELECT latest_version, force_update FROM app_versions ORDER BY updated_at DESC LIMIT 1;
```

## Complete flag inventory

### DB flags (settings table — flip via webdash Admin → Feature flags, no deploy)

| Flag | Gates | Symptom when OFF | Prod should be |
|---|---|---|---|
| `vehicle_log_enabled` | ALL /api/vehicles endpoints | Security vehicle widget dead; MD vehicle register 403s | ON (your step 2) |
| `home_config_enabled` | Server-driven home tiles (/api/home/config) | App falls back to built-in hardcoded home layout | ON once field-verified |
| `notif_batching_enabled` | Manager notification digest batching | Managers get every notification individually (noisier, not broken) | Your call |
| `beacon_first_mode` | Beacon zone decides punch; GPS demoted to evidence | Launch BEACON-WINS ladder (byte-identical to v1.0.17 behaviour) | OFF until you order it |
| `dup_window_minutes/zone/category` | Duplicate-incident clustering rules | n/a (tunables, defaults 30m/true/true) | defaults |

**⚠️ Demo bypass:** demo accounts skip `vehicle_log_enabled` and `home_config_enabled`.
A feature working under Demo@8709 proves NOTHING about real users. This is exactly
how `vehicle_log_enabled` sat dark for days.

### App-version row (webdash Admin → App version)

| Field | Effect |
|---|---|
| `latest_version` | Semantic compare vs the app's own version |
| `force_update` | ON → app below latest_version gets the non-dismissible block screen (builds ≥1.0.22 only; older builds show the dismissible banner) |
| `apk_url` | The button target on banner/block screen |

### Env toggles (backend/.env — need `docker compose restart` to change)

| Toggle | Effect | Prod should be |
|---|---|---|
| `OTP_MODE` | demo / smsgatewayhub — unset = API refuses to start | smsgatewayhub |
| `DEMO_OTP_ENABLED` | Fixed-OTP backdoor for whitelisted numbers | OFF (or whitelist-only, your standing config) |
| `ALLOW_NEW_REGISTRATION` | Unknown numbers may self-register | ON |
| `BACKUP_UPLOAD_ENABLED` | 4-hourly pg_dump → R2 | ON (unset = ON; only sandbox sets 0) |
| `FILE_STORAGE_MODE` | local / s3 | s3 |
| Credentials | `OPENAI_API_KEY` (voice), `SMSGATEWAYHUB_API_KEY` (OTP), AWS keys (face match), `ANPR_API_KEY` (plates), S3/R2 keys (media+backups) | all SET |

## Production snapshot (restored backup 2026-07-31 20:30 IST)

DB flags — REAL production values:
- `vehicle_log_enabled` **OFF** ← the MD register 403; your step 2 flips it
- `home_config_enabled` **OFF** ← also silently dark; server-driven home never reached real users
- `notif_batching_enabled` **OFF** (default, no field impact)
- `beacon_first_mode` **OFF** (correct — ships OFF by design)
- app_versions: `1.0.18`, `force_update=ON`

Env section of the snapshot run shows SANDBOX values — run the command on EC2 for
the real ones. The one prod-relevant known gap: `OPENAI_API_KEY` goes into prod
.env during your deploy step (AUTOPSY §2), or voice STT/TTS will 503.

"""One-screen production truth: every feature flag / toggle and its live value.

Run on the EC2 box:
    docker compose exec -T api python scripts/flag_audit.py

Reads the SAME sources the running API reads: the settings/app_versions tables
via the app's own engine, and app.config.settings for env-level toggles.
Read-only — touches nothing.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.config import settings as env
from app.database import engine

ON, OFF = "\033[92mON \033[0m", "\033[91mOFF\033[0m"


def b(v) -> str:
    return ON if v else OFF


def secret(v) -> str:
    return "\033[92mSET\033[0m" if v else "\033[91mMISSING\033[0m"


async def main() -> None:
    async with engine.connect() as conn:
        s = (await conn.execute(text(
            "SELECT beacon_first_mode, home_config_enabled, vehicle_log_enabled, "
            "notif_batching_enabled, dup_window_minutes, dup_same_zone, dup_same_category, "
            "radius_meters FROM settings LIMIT 1"
        ))).mappings().first()
        v = (await conn.execute(text(
            "SELECT latest_version, force_update, apk_url FROM app_versions "
            "ORDER BY updated_at DESC LIMIT 1"
        ))).mappings().first()

    print("=" * 62)
    print("DB FEATURE FLAGS (settings table — live, what real users get)")
    print("=" * 62)
    if s is None:
        print("!! settings row MISSING — seed not run !!")
    else:
        print(f"  vehicle_log_enabled     {b(s['vehicle_log_enabled'])}   gate register + MD vehicles view")
        print(f"  home_config_enabled     {b(s['home_config_enabled'])}   server-driven home tiles")
        print(f"  notif_batching_enabled  {b(s['notif_batching_enabled'])}   manager notification digests")
        print(f"  beacon_first_mode       {b(s['beacon_first_mode'])}   beacon zone decides punch (GPS secondary)")
        print(f"  dup clustering          window={s['dup_window_minutes']}m same_zone={s['dup_same_zone']} same_category={s['dup_same_category']}")
        print(f"  geofence radius         {s['radius_meters']} m")
    print()
    print("APP VERSION (app_versions table)")
    if v is None:
        print("  !! no app_versions row — update banner/force-update INERT !!")
    else:
        print(f"  latest_version          {v['latest_version']}")
        print(f"  force_update            {b(v['force_update'])}   blocks app below latest_version")
        print(f"  apk_url                 {v['apk_url'] or '(none — banner has no download link)'}")
    print()
    print("ENV TOGGLES (what the API process actually loaded)")
    print(f"  OTP_MODE                {env.otp_mode or '!! UNSET — logins will fail !!'}")
    print(f"  DEMO_OTP_ENABLED        {b(env.demo_otp_enabled)}   fixed-OTP backdoor (whitelist={len(env.demo_otp_whitelist_set)} numbers)")
    print(f"  ALLOW_NEW_REGISTRATION  {b(env.allow_new_registration)}   unknown numbers may self-register")
    print(f"  BACKUP_UPLOAD_ENABLED   {b(env.backup_upload_enabled)}   4-hourly dump → R2")
    print(f"  FILE_STORAGE_MODE       {env.file_storage_mode}")
    print()
    print("CREDENTIALS PRESENT (value hidden)")
    print(f"  OPENAI_API_KEY          {secret(env.openai_api_key)}  (voice STT/TTS, AI describe)")
    print(f"  EMERGENT_LLM_KEY        {secret(env.emergent_llm_key)}  (sandbox fallback only)")
    print(f"  SMSGATEWAYHUB_API_KEY   {secret(env.smsgatewayhub_api_key)}  (real OTP SMS)")
    print(f"  AWS access keys         {secret(env.aws_access_key_id and env.aws_secret_access_key)}  (Rekognition face match)")
    print(f"  ANPR_API_KEY            {secret(env.anpr_api_key)}  (plate reading)")
    print(f"  S3/R2 keys              {secret(env.s3_access_key_id and env.s3_secret_access_key)}  (media + backups)")
    print("=" * 62)
    print("NOTE: demo accounts BYPASS vehicle_log_enabled/home_config_enabled —")
    print("demo working ≠ real users working. Trust this screen, not the demo.")
    await engine.dispose()


asyncio.run(main())

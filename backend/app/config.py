import re
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent

# Prompt 21 Bug-1 env hygiene: fields where a trailing " # comment" can safely be
# stripped. Secrets, URLs and OTP_TEMPLATE_TEXT are deliberately EXCLUDED — '#'
# may be a legitimate character there ({#var#} in the DLT template).
_COMMENT_STRIP_FIELDS = {
    "otp_mode", "demo_otp_enabled", "demo_otp", "demo_otp_whitelist",
    "allow_new_registration", "file_storage_mode", "aws_region",
    "smsgatewayhub_sender_id", "smsgatewayhub_dlt_template_id", "smsgatewayhub_entity_id",
    "otp_max_per_window", "otp_window_minutes", "otp_resend_cooldown_seconds",
    "escalation_hours", "access_token_hours", "refresh_token_days",
    "ai_cache_ttl", "backup_keep_last", "s3_bucket",
}

# Non-string fields where an EMPTY .env value (e.g. "DEMO_OTP_ENABLED=") must mean
# "use the default" instead of an opaque pydantic bool/int parse crash.
_EMPTY_USES_DEFAULT = {
    "demo_otp_enabled": False,
    "allow_new_registration": True,
    "otp_max_per_window": 5,
    "otp_window_minutes": 10,
    "otp_resend_cooldown_seconds": 45,
    "access_token_hours": 24,
    "refresh_token_days": 30,
    "escalation_hours": 48,
    "ai_cache_ttl": 86400,
    "backup_keep_last": 14,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"), extra="ignore", case_sensitive=False
    )

    @field_validator("*", mode="before")
    @classmethod
    def _sanitize_env_value(cls, v, info):
        """Defensive .env hygiene (Bug 1): strip whitespace/CR, one layer of matching
        outer quotes, and (for simple fields only) trailing inline comments — the
        deployed stack's env parser may pass these through verbatim."""
        if not isinstance(v, str):
            return v
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
            v = v[1:-1].strip()
        if info.field_name in _COMMENT_STRIP_FIELDS:
            v = re.split(r"\s+#", v, maxsplit=1)[0].strip()
        if v == "" and info.field_name in _EMPTY_USES_DEFAULT:
            return _EMPTY_USES_DEFAULT[info.field_name]
        return v

    database_url: str
    # Engine pool sizing (per uvicorn worker). Defaults are the Neon-era values
    # (high RTT needed big pools behind pgbouncer). On low-RTT RDS set in .env:
    # DB_POOL_SIZE=10 DB_MAX_OVERFLOW=20 (2 workers x 30 = 60 conns, well under
    # db.t4g.micro's ~110 max_connections).
    db_pool_size: int = 40
    db_max_overflow: int = 110
    redis_url: str
    celery_broker_url: str = "redis://127.0.0.1:6379/1"
    celery_result_backend: str = "redis://127.0.0.1:6379/2"
    jwt_secret: str
    # NO default mode (Bug 1 fix): an unset/unreadable OTP_MODE must FAIL FAST at
    # startup (see app.main), never silently fall back to demo.
    otp_mode: str = ""  # demo | msg91 | smsgatewayhub | whatsapp — REQUIRED
    # OTP send rate limiting (all overridable via .env):
    otp_max_per_window: int = 5          # sends allowed per phone per window
    otp_window_minutes: int = 10         # rolling window length
    otp_resend_cooldown_seconds: int = 45  # min gap between two sends (0 = off)
    msg91_auth_key: str = ""
    msg91_otp_template_id: str = ""
    anpr_api_url: str = ""
    anpr_api_key: str = ""
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket: str = "hogoplus-fs"
    file_storage_mode: str = "local"  # local | s3
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "ap-south-1"
    emergent_llm_key: str = ""
    smsgatewayhub_api_key: str = ""
    smsgatewayhub_sender_id: str = ""
    smsgatewayhub_dlt_template_id: str = ""
    smsgatewayhub_entity_id: str = ""  # optional; attached only when provided
    otp_template_text: str = ""  # EXACT DLT-approved template with {#var#} placeholders
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_cache_dir: str = str(ROOT_DIR / ".fastembed_cache")
    ai_cache_ttl: int = 86400
    backup_keep_last: int = 14
    # SECURITY (Bug 1): the fixed demo OTP is accepted ONLY when this is explicitly
    # read as true from the environment — default is OFF.
    demo_otp_enabled: bool = False
    demo_otp: str = "123456"
    # contest guard: when false, OTP requests from unknown numbers are blocked (no SMS)
    allow_new_registration: bool = True
    demo_otp_whitelist: str = ""  # comma-separated +91 numbers allowed to use DEMO_OTP

    @property
    def demo_otp_whitelist_set(self) -> frozenset[str]:
        return frozenset(p.strip() for p in self.demo_otp_whitelist.split(",") if p.strip())
    escalation_hours: int = 48
    upload_dir: str = str(ROOT_DIR / "uploads")

    # JWT lifetimes
    access_token_hours: int = 24
    refresh_token_days: int = 30


settings = Settings()

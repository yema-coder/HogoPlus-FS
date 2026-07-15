from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"), extra="ignore", case_sensitive=False
    )

    database_url: str
    redis_url: str
    celery_broker_url: str = "redis://127.0.0.1:6379/1"
    celery_result_backend: str = "redis://127.0.0.1:6379/2"
    jwt_secret: str
    otp_mode: str = "demo"  # demo | msg91 | smsgatewayhub | whatsapp
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
    demo_otp_enabled: bool = True
    demo_otp: str = "123456"
    escalation_hours: int = 48
    upload_dir: str = str(ROOT_DIR / "uploads")

    # JWT lifetimes
    access_token_hours: int = 24
    refresh_token_days: int = 30


settings = Settings()

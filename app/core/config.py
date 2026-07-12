from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Elchi API"
    environment: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/elchi"

    secret_key: str = Field(default="change-this-secret-key", min_length=16)
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30
    jwt_algorithm: str = "HS256"
    mock_otp_code: str = "00000"
    otp_length: int = 5
    otp_expire_seconds: int = 120
    otp_max_send_requests: int = 5
    otp_send_window_minutes: int = 30
    otp_resend_cooldown_seconds: int = 60
    otp_max_verify_attempts: int = 5
    dev_mock_otp: str = "12345"
    super_admin_phone: str | None = "+998900000001"

    upload_dir: str = "storage/uploads"
    max_image_upload_mb: int = 5
    max_document_upload_mb: int = 10
    public_upload_base_url: str = "/uploads"

    google_maps_api_key: str | None = None
    google_maps_country: str = "uz"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173,http://0.0.0.0:5173"
    cors_origin_regex: str | None = (
        r"https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})(:\d+)?"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ELCHI_",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

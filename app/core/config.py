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
    mock_otp_code: str = "0000"
    # 4 digits, matching the Eskiz-approved Elchi template. Keep in sync with
    # the clients' OTP_LENGTH (VITE_OTP_LENGTH / EXPO_PUBLIC_OTP_LENGTH).
    otp_length: int = 4
    otp_expire_seconds: int = 180
    otp_max_send_requests: int = 5
    otp_send_window_minutes: int = 30
    otp_resend_cooldown_seconds: int = 60
    otp_max_verify_attempts: int = 5
    # Anti SMS-pumping: cap requests per source IP and a hard global daily
    # ceiling so a distributed attack can't exceed a known SMS spend.
    otp_max_requests_per_ip: int = 15
    otp_ip_window_minutes: int = 60
    otp_global_daily_cap: int = 2000
    dev_mock_otp: str = "1234"
    # ── App-store reviewer access ────────────────────────────────────────────
    # Google and Apple reviewers cannot receive an SMS to an Uzbek number, so
    # without this they never get past the login screen and the submission is
    # rejected. These specific phones accept a fixed code instead. Both values
    # must be set for the path to exist at all, it applies to no other number,
    # and every use is logged. Clear them once review is complete.
    review_login_phones: str = ""
    review_login_otp: str | None = None
    super_admin_phone: str | None = "+998900000001"

    # ── SMS / OTP delivery via Eskiz.uz ──────────────────────────────────────
    # sms_enabled turns on real delivery; when off, OTPs stay dev-mock only.
    # sms_test_mode sends the pre-approved test template with a fixed code
    # (needed until the production template is moderated by Eskiz).
    sms_enabled: bool = False
    sms_test_mode: bool = True
    eskiz_base_url: str = "https://notify.eskiz.uz/api"
    eskiz_email: str | None = None
    eskiz_password: str | None = None
    eskiz_from: str = "4546"  # Eskiz's default test sender id
    otp_message_template: str = "Elchi platformasiga kirish uchun tasdiqlash kodi: {code}"
    # Eskiz-approved template ('...kodi: %d') — {code} is the variable part.
    sms_test_message: str = "Dunyo Taxi platformasiga kirish uchun tasdiqlash kodi: {code}"

    upload_dir: str = "storage/uploads"
    max_image_upload_mb: int = 5
    max_document_upload_mb: int = 10
    public_upload_base_url: str = "/uploads"

    google_maps_api_key: str | None = None
    google_maps_country: str = "uz"
    yandex_geocoder_api_key: str | None = None
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

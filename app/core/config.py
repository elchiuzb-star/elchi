from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.contracts.crypto import PURPOSE_BOOKING_PROOF_CODE, PURPOSE_CURSOR_SIGNING, KeyRing, build_keyring, derive_subkey

# ELCHI_ENVIRONMENT allowlist (wave 1.5 BR). The first four are the DB marker values
# (app.modules.platform.service.DeploymentEnvironment); "local" is the developer default from
# .env.example and maps to development. Anything else (including "prod") fails Settings()
# and therefore both app start-up and alembic/env.py: an ambiguous environment must never
# silently disable production guards.
ALLOWED_ENVIRONMENTS: frozenset[str] = frozenset({"production", "staging", "development", "test", "local"})


class Settings(BaseSettings):
    app_name: str = "Elchi API"
    environment: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/elchi"
    # Redis is non-durable (ADR-0012): unset -> readiness reports redis "not_configured".
    redis_url: str | None = None

    secret_key: str = Field(default="change-this-secret-key", min_length=16)
    # N5 / ADR-0018 key rotation (docs/ops/SECRET_ROTATION.md). Comma-separated, newest first;
    # accepted for verification only (proof-code keyring), never used to sign.
    previous_secret_keys: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Dedicated masters; unset -> the purpose subkey is derived from secret_key.
    proof_code_key: str | None = Field(default=None, min_length=32)
    cursor_signing_key: str | None = Field(default=None, min_length=32)
    access_token_expire_minutes: int = 60
    #: ADR-0021: staff tokens are short-lived because a stolen staff token reaches money commands. Marketplace
    #: accounts keep the 60 minutes above - shortening those would only make the frozen client refresh more.
    staff_access_token_expire_minutes: int = 15
    #: ADR-0021 rollout stage: "audit_only" (record, never block) -> "enforce_privileged" (super_admin and
    #: finance must step up) -> "enforce_all". The default is audit_only on purpose: enforcement is a
    #: deliberate operational step, not something that switches itself on when staff are added.
    staff_mfa_mode: str = "audit_only"
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
    # Prefix of the stored DB value for uploads (`/uploads/<key>`). Nothing is
    # served publicly under it any more; keep it as `/uploads` for old rows.
    public_upload_base_url: str = "/uploads"
    # HMAC key for short-lived signed download URLs (GET /api/v1/files/<key>).
    # Unset -> derived from secret_key with domain separation (never the raw secret).
    file_url_signing_key: str | None = Field(default=None, min_length=32)
    file_url_ttl_seconds: int = Field(default=900, ge=60, le=86400)

    @field_validator("environment", mode="before")
    @classmethod
    def environment_in_allowlist(cls, value: object) -> str:
        text = value.strip().lower() if isinstance(value, str) else ""
        if text not in ALLOWED_ENVIRONMENTS:
            raise ValueError(
                f"ELCHI_ENVIRONMENT must be one of {sorted(ALLOWED_ENVIRONMENTS)}, got {value!r}"
            )
        return text

    @field_validator("previous_secret_keys", mode="before")
    @classmethod
    def split_previous_secret_keys(cls, value: object) -> object:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("proof_code_key", "cursor_signing_key", mode="before")
    @classmethod
    def blank_dedicated_key_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("file_url_signing_key", mode="before")
    @classmethod
    def blank_signing_key_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    yandex_geocoder_api_key: str | None = None
    # Geosuggest is a separate Yandex product with its own key: the geocoder answers addresses,
    # suggest answers place names ("10-sonli maktab"), which is what a person actually types.
    yandex_suggest_api_key: str | None = None
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


def proof_code_keyring(config: "Settings | None" = None) -> KeyRing:
    """Booking proof-code keyring (N5): current master plus ELCHI_PREVIOUS_SECRET_KEYS for the
    KEY_ROTATION_VERIFICATION_WINDOW. Use with ``crypto.derive_proof_code`` / ``verify_proof_code``."""
    config = config or settings
    return build_keyring(
        PURPOSE_BOOKING_PROOF_CODE,
        config.proof_code_key or config.secret_key,
        previous_masters=config.previous_secret_keys,
    )


def cursor_signing_secret(config: "Settings | None" = None) -> bytes:
    """Cursor HMAC key: derived from ELCHI_CURSOR_SIGNING_KEY when set, else from secret_key.
    Previous keys are not accepted (an old cursor fails and the client restarts pagination)."""
    config = config or settings
    return derive_subkey(config.cursor_signing_key or config.secret_key, PURPOSE_CURSOR_SIGNING)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

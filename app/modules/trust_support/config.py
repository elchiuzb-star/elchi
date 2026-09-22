"""Support settings (env prefix ``ELCHI_SUPPORT_``), kept out of ``app/core/config.py`` (integrator-owned).

Variables (optional; real values are a pending user decision, U7):
    ELCHI_SUPPORT_PHONE       support phone shown by S13; unset -> ``available=false``
    ELCHI_SUPPORT_HOURS_TEXT  free text such as "Du-Sha 09:00-18:00"

§5.2 / §16: the API never promises a 24/7 operator or a response time (``trust.SUPPORT_PROMISES_RESPONSE_TIME``).
An hours text that looks like such a promise is not shown (logged instead) - there is no default text.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("elchi.trust_support")

# "24/7", "24 soat", "kun-u tun", "круглосуточно", "javob N daqiqada" ... - never shown (§16).
_PROMISE_PATTERNS = re.compile(
    r"24\s*/\s*7|24\s*(soat|saat|час)|kun\s*-?\s*u\s*-?\s*tun|kecha\s*-?\s*kunduz|круглосуточ|без\s+выходных|"
    r"(javob|ответ)\w*\s.*\d+\s*(daqiqa|minut|мин|soat|час)",
    re.IGNORECASE,
)


class SupportSettings(BaseSettings):
    phone: str | None = None
    hours_text: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_prefix="ELCHI_SUPPORT_", case_sensitive=False, extra="ignore"
    )


@lru_cache
def get_support_settings() -> SupportSettings:
    return SupportSettings()


def promises_response_time(text: str | None) -> bool:
    return bool(text and _PROMISE_PATTERNS.search(text))


def support_contacts(settings: SupportSettings | None = None) -> tuple[bool, str | None, str | None]:
    """``(available, phone, hours_text)`` for S13. No phone configured -> not available; no invented hours."""
    cfg = settings or get_support_settings()
    phone = (cfg.phone or "").strip() or None
    hours = (cfg.hours_text or "").strip() or None
    if hours is not None and promises_response_time(hours):
        logger.warning("ELCHI_SUPPORT_HOURS_TEXT looks like a 24/7 or response-time promise; not shown (spec §16)")
        hours = None
    if phone is None:
        return False, None, None
    return True, phone, hours

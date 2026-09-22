"""SMS delivery via Eskiz.uz.

Eskiz issues a bearer token from email+password (valid ~30 days); we cache it in
memory and re-login on a 401. Sending is a simple form POST. Everything degrades
gracefully — a misconfigured or unreachable gateway returns False instead of
raising, so OTP requests never hard-fail on SMS problems.

Docs: https://documenter.getpostman.com/view/663428/RzfmES4z
"""

from __future__ import annotations

import logging
import threading

import httpx

from app.core.config import settings
from app.services.review_accounts import is_review_account_phone

logger = logging.getLogger("elchi.sms")

_REQUEST_TIMEOUT = 10.0
_token_lock = threading.Lock()
_cached_token: str | None = None


def is_configured() -> bool:
    return bool(settings.sms_enabled and settings.eskiz_email and settings.eskiz_password)


def _login() -> str | None:
    """Exchange email+password for a bearer token."""
    try:
        response = httpx.post(
            f"{settings.eskiz_base_url}/auth/login",
            data={"email": settings.eskiz_email, "password": settings.eskiz_password},
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        token = response.json().get("data", {}).get("token")
        if not token:
            logger.error("Eskiz login returned no token: %s", response.text[:200])
        return token
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("Eskiz login failed: %s", exc)
        return None


def _get_token(force_refresh: bool = False) -> str | None:
    global _cached_token
    with _token_lock:
        if _cached_token and not force_refresh:
            return _cached_token
        _cached_token = _login()
        return _cached_token


def _post_message(token: str, mobile_phone: str, message: str) -> httpx.Response | None:
    try:
        return httpx.post(
            f"{settings.eskiz_base_url}/message/sms/send",
            data={"mobile_phone": mobile_phone, "message": message, "from": settings.eskiz_from},
            headers={"Authorization": f"Bearer {token}"},
            timeout=_REQUEST_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        logger.error("Eskiz send request failed: %s", exc)
        return None


def send_sms(phone: str, message: str) -> bool:
    """Send an SMS. Returns True on success, False otherwise (never raises)."""
    # Store-review accounts never receive SMS (defense in depth; callers check too).
    if is_review_account_phone(phone):
        logger.info("SMS suppressed for store-review phone")
        return False
    if not is_configured():
        return False
    mobile_phone = phone.lstrip("+")  # Eskiz expects 998XXXXXXXXX

    token = _get_token()
    if not token:
        return False

    response = _post_message(token, mobile_phone, message)
    # Token likely expired — refresh once and retry.
    if response is not None and response.status_code == 401:
        token = _get_token(force_refresh=True)
        if token:
            response = _post_message(token, mobile_phone, message)

    if response is None:
        return False
    if response.status_code in (200, 201):
        return True
    logger.error("Eskiz send failed (%s): %s", response.status_code, response.text[:200])
    return False

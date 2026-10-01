"""Tracking module settings (``ELCHI_TRACKING_*``; env samples are added by the integrator)."""

from __future__ import annotations

import os

PUBLIC_URL_TEMPLATE_ENV = "ELCHI_TRACKING_PUBLIC_URL_TEMPLATE"
# K7 path on this API. A web page for recipients can be put in front of it later (template with ``{token}``).
DEFAULT_PUBLIC_URL_TEMPLATE = "/api/v2/public/tracking/{token}"
#: Path of the recipient page on the public web site (ELCHI_PUBLIC_WEB_BASE_URL), used only when no template is set.
WEB_PATH_TEMPLATE = "/t/{token}"


def public_tracking_url(token: str) -> str:
    """The recipient link shown once at K5. The token itself is never stored or logged.

    Priority: ``ELCHI_TRACKING_PUBLIC_URL_TEMPLATE`` (must contain ``{token}``) -> ``{ELCHI_PUBLIC_WEB_BASE_URL}/t/{token}``
    -> the relative API path (the behaviour before the base URL existed).
    """
    from app.core.config import public_web_base_url

    template = (os.environ.get(PUBLIC_URL_TEMPLATE_ENV) or "").strip()
    if "{token}" not in template:
        base = public_web_base_url()
        template = f"{base}{WEB_PATH_TEMPLATE}" if base else DEFAULT_PUBLIC_URL_TEMPLATE
    return template.replace("{token}", token)

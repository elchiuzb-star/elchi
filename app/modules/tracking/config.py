"""Tracking module settings (``ELCHI_TRACKING_*``; env samples are added by the integrator)."""

from __future__ import annotations

import os

PUBLIC_URL_TEMPLATE_ENV = "ELCHI_TRACKING_PUBLIC_URL_TEMPLATE"
# K7 path on this API. A web page for recipients can be put in front of it later (template with ``{token}``).
DEFAULT_PUBLIC_URL_TEMPLATE = "/api/v2/public/tracking/{token}"


def public_tracking_url(token: str) -> str:
    """The recipient link shown once at K5. The token itself is never stored or logged."""
    template = (os.environ.get(PUBLIC_URL_TEMPLATE_ENV) or "").strip()
    if "{token}" not in template:
        template = DEFAULT_PUBLIC_URL_TEMPLATE
    return template.replace("{token}", token)

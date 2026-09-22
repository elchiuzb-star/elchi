"""API v2 package (integrator-owned; ADR-0001, ADR-0005).

Deliberately light: importing ``app.api.v2`` (e.g. for ``app.api.v2.web``) must not import
module routers, otherwise ``app.modules.<m>.api -> app.api.v2.web`` would be circular.

* ``app.api.v2.router`` — aggregated ``api_router`` and ``configure_v2_ports``.
* ``app.api.v2.web`` — shared v2 HTTP plumbing (moved from ``app.modules.identity.web``).
* ``from app.api.v2 import api_router`` keeps working (resolved lazily).
"""

from __future__ import annotations

from typing import Any

API_V2_PREFIX = "/api/v2"

__all__ = ["API_V2_PREFIX", "api_router"]


def __getattr__(name: str) -> Any:
    if name == "api_router":
        from app.api.v2.router import api_router

        return api_router
    raise AttributeError(f"module 'app.api.v2' has no attribute {name!r}")

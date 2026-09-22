"""Geo module settings (env prefix ``ELCHI_GEO_``), kept out of ``app/core/config.py`` (H0-owned).

Variables (all optional):
    ELCHI_GEO_ROUTING_PROVIDER    disabled (default) | fake | osrm | geoapify
    ELCHI_GEO_OSRM_BASE_URL       default http://127.0.0.1:5000 (our own container)
    ELCHI_GEO_GEOAPIFY_API_KEY    server-side secret; never sent to clients
    ELCHI_GEO_GEOAPIFY_BASE_URL   default https://api.geoapify.com/v1/routing
    ELCHI_GEO_ROUTING_TIMEOUT_S   default 6
    ELCHI_GEO_ROUTING_CACHE_TTL_S default 86400

Decision 24 (wave 1.5): in production NO routing provider is enabled.
* ``geoapify`` (hosted) needs a legal/terms review (data leaves the country; permanent storage of
  provider-derived geometry needs terms confirmation) - not done.
* ``fake`` would produce fake matches (AC35).
* ``osrm`` is **ours**: an OpenStreetMap extract served by a container beside the database, so no
  coordinate leaves the machine and there is no third party to review. It is the provider that can
  lift decision 24 - but doing so is still an ADR and a code change here, not a setting, because
  production must not start routing because somebody edited an environment file.
Production detection is ``platform.service.is_production(session)`` (settings OR DB marker, fail
closed). Lifting the guard requires the review result, an ADR update and a code change; there is
deliberately no environment switch. Until then G5 answers ``503 ROUTING_UNAVAILABLE`` in production
and detours are reported unavailable, while matches on existing stops keep working.
Consequence: provider-derived geometry is stored only outside production.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.modules.geo.routing.base import DisabledRoutingProvider, RoutingProvider
from app.modules.geo.routing.fake import FakeRoutingProvider
from app.modules.geo.routing.geoapify import DEFAULT_BASE_URL, GeoapifyRoutingProvider
from app.modules.geo.routing.osrm import DEFAULT_BASE_URL as OSRM_DEFAULT_BASE_URL
from app.modules.geo.routing.osrm import OsrmRoutingProvider

PRODUCTION_PROVIDER_REFUSAL = "routing_provider_not_approved_for_production"


class GeoSettings(BaseSettings):
    routing_provider: Literal["disabled", "fake", "osrm", "geoapify"] = "disabled"
    osrm_base_url: str = OSRM_DEFAULT_BASE_URL
    geoapify_api_key: SecretStr | None = None
    geoapify_base_url: str = DEFAULT_BASE_URL
    #: Dev/test only: widen the Q88 projection radius so any two marked places resolve on a synthetic
    #: corridor (scripts/seed_dev_nationwide.py). The stored column stays inside its CHECK (<= 25 km) -
    #: this only relaxes what the *resolver* tolerates, and `corridor_point_offset_m` ignores it outside
    #: development. It is a testing affordance, never a rollout switch.
    dev_point_offset_m: int | None = Field(default=None, ge=100, le=1_000_000)
    routing_timeout_s: float = Field(default=6.0, gt=0, le=30)
    routing_cache_ttl_s: int = Field(default=86400, ge=0, le=7 * 86400)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ELCHI_GEO_",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_geo_settings() -> GeoSettings:
    return GeoSettings()


def build_routing_provider(geo_settings: GeoSettings | None = None, *, production: bool) -> RoutingProvider:
    """``production`` must come from ``platform.service.is_production(session)``."""
    if production:
        return DisabledRoutingProvider(PRODUCTION_PROVIDER_REFUSAL)
    cfg = geo_settings or get_geo_settings()
    if cfg.routing_provider == "fake":
        return FakeRoutingProvider()
    if cfg.routing_provider == "osrm":
        return OsrmRoutingProvider(base_url=cfg.osrm_base_url, timeout_s=cfg.routing_timeout_s)
    if cfg.routing_provider == "geoapify":
        key = cfg.geoapify_api_key.get_secret_value() if cfg.geoapify_api_key else ""
        if not key:
            return DisabledRoutingProvider("not_configured")
        return GeoapifyRoutingProvider(key, base_url=cfg.geoapify_base_url, timeout_s=cfg.routing_timeout_s)
    return DisabledRoutingProvider("not_configured")

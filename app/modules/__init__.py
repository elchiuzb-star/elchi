"""Stage-2 domain modules (ADR-0001).

Model registration is explicit and integrator-owned: importing ``app.modules`` does not
import any models by itself, so a submodule import never registers unrelated tables.
``alembic/env.py`` and ``app.main`` call :func:`import_models` so ``Base.metadata`` (and
the ORM drift check) sees every wired v2 table.
"""

from __future__ import annotations

from importlib import import_module

# Wave 1 (integration passes 1+2): A3 platform + wallet, A2 geo, A1 identity + trips + marketplace.
WIRED_MODEL_MODULES: tuple[str, ...] = (
    "app.modules.platform.models",
    "app.modules.wallet.models",
    "app.modules.geo.models",
    "app.modules.identity.models",
    "app.modules.trips.models",
    "app.modules.marketplace.models",
    # Wave 2 (bookings integration pass): A4.
    "app.modules.bookings.models",
    # Wave 3 (integration pass): A6 tracking, A7 communications, A12 trust & support, A5 marketplace feed.
    "app.modules.tracking.models",
    "app.modules.communications.models",
    "app.modules.trust_support.models",
    "app.modules.marketplace.feed.models",
    # Wave 4 (integration pass): A13 operations and growth.
    "app.modules.operations.models",
)

# Modules whose models exist but are not wired yet (none after pass 2).
PENDING_MODEL_MODULES: tuple[str, ...] = ()


def import_models() -> None:
    """Import every wired v2 model module (idempotent)."""
    for name in WIRED_MODEL_MODULES:
        import_module(name)

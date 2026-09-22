"""Operator gate CLI for scripts/deploy.sh (wave 1.7 NEW-1, Q48, Q56, Q57).

    python -m app.ops.gates status

Prints one JSON object and exits 0 (the caller decides):

    {"hooks": {"<module>.<fn>": {"group": "invariants"|"q48_gate", "available": bool,
                                 "ok": bool, "failed": [...], "notices": [...]} ...},
     "q48_gate": {"available": bool, "ok": bool|null, "failed": [...]},
     "invariant_failures_excluding_q48": [...],
     "enabled_v2_service_flags": [...]}

Runs with the app role (ELCHI_DATABASE_URL), read-only (every hook session is rolled back).
Details stay here; ``/health/ready`` only exposes status names.
"""

from __future__ import annotations

import argparse
import json
import sys

V2_SERVICE_FLAGS = (
    "passenger_enabled",
    "parcel_enabled",
    "driver_listing_enabled",
    "corridor_matching_enabled",
    "tracking_enabled",
    "card_payments_enabled",
)


def enabled_v2_service_flags(connection) -> list[str]:  # noqa: ANN001 - SQLAlchemy Connection
    from sqlalchemy import text

    exists = connection.execute(text("SELECT to_regclass('public.feature_flag_values') IS NOT NULL")).scalar()
    if not exists:
        return []
    rows = connection.execute(
        text(
            "SELECT flag_key || ':' || scope_type || ':' || scope_ref FROM feature_flag_values "
            "WHERE enabled AND flag_key = ANY(:keys) ORDER BY 1"
        ),
        {"keys": list(V2_SERVICE_FLAGS)},
    ).scalars()
    return list(rows)


def status(probe=None, engine=None) -> dict:  # noqa: ANN001
    from app.api.health_probes import build_probe_engine, get_readiness_probe

    probe = probe or get_readiness_probe()
    if engine is None:
        from app.core.config import settings

        engine = build_probe_engine(settings.database_url)
    hooks = probe.evaluate_hooks(engine)
    gate = next((h for h in hooks.values() if h["group"] == "q48_gate" and h.get("available")), None)
    failures: list[str] = []
    for name, detail in hooks.items():
        if detail["group"] != "invariants" or not detail.get("available"):
            continue
        if "error" in detail:
            failures.append(f"{name}:error:{detail['error']}")
        elif not detail.get("ok"):
            failures.extend(f"{name}:{item}" for item in detail.get("failed") or ["failed"])
    with engine.connect() as conn:
        flags = enabled_v2_service_flags(conn)
    return {
        "hooks": hooks,
        "q48_gate": {
            "available": gate is not None,
            "ok": None if gate is None else (gate.get("ok") if "error" not in gate else False),
            "failed": [] if gate is None else gate.get("failed", [gate.get("error", "error")]),
        },
        "invariant_failures_excluding_q48": failures,
        "enabled_v2_service_flags": flags,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ops.gates")
    parser.add_argument("command", choices=["status"])
    parser.parse_args(argv)
    print(json.dumps(status(), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Read-only geo consistency checks (wave 1.7, BR F1).

CLI::

    python -m app.modules.geo.checks q47      # exit 0: none, exit 1: violations listed as JSON lines

Staff API: ``GET /api/v2/admin/geo/checks/q47`` (``ops.view``). Readiness/alerts may include
``geo.service.production_invariant_notices(db)`` as a notice (never a 503).

Q47 check (ADR-0028 replaces its stop conditions): a corridor in ``pilot`` or ``active`` must have a confirmed road.
New changes are enforced by the service (``start_pilot`` / ``activate`` guards); this finds corridors that already
violate it.

Runbook (repair a violating corridor):
1. Find it: ``python -m app.modules.geo.checks q47`` or the staff endpoint.
2. Take it out of the public states with a reason:
   ``active`` -> ``PATCH /api/v2/admin/corridors/{id}`` ``rollout_state=pilot`` (``return_to_pilot``), then
   ``pilot`` -> ``rollout_state=internal`` (``return_to_internal``). Existing bookings keep running (AC38);
   the corridor leaves the public list, so no new public listings.
3. Confirm a road from A to B while ``internal`` (``POST /routes/preview`` + ``/routes/{id}/confirm``).
4. Return it: ``rollout_state=pilot`` (``start_pilot`` re-checks), then ``activate`` if it was active.
5. Re-run the check; it must report no violations.
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.modules.geo.checks")
    sub = parser.add_subparsers(dest="check", required=True)
    sub.add_parser("q47", help="corridors in pilot/active without a confirmed road (ADR-0028)")
    args = parser.parse_args(argv)

    from app.db.session import SessionLocal
    from app.modules.geo import service

    if args.check == "q47":
        with SessionLocal() as db:
            violations = service.find_q47_violations(db)
        for violation in violations:
            print(json.dumps(violation.as_dict(), sort_keys=True))
        print(f"q47: {len(violations)} corridor(s) violating", file=sys.stderr)
        return 1 if violations else 0
    return 2  # pragma: no cover - argparse rejects unknown checks


if __name__ == "__main__":
    raise SystemExit(main())

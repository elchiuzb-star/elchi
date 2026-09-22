"""Read-only geo consistency checks (wave 1.7, BR F1).

CLI::

    python -m app.modules.geo.checks q47      # exit 0: none, exit 1: violations listed as JSON lines

Staff API: ``GET /api/v2/admin/geo/checks/q47`` (``ops.view``). Readiness/alerts may include
``geo.service.production_invariant_notices(db)`` as a notice (never a 503).

Q47 check: a corridor in ``pilot`` or ``active`` must have at least two active stops, each with meeting
evidence (a meeting note or a photo, Q27). New changes are enforced by the service and the 0046/0053 DB
triggers; this finds corridors that already violate it (rows written before 0046, or with triggers
bypassed).

Runbook (repair a violating corridor):
1. Find it: ``python -m app.modules.geo.checks q47`` or the staff endpoint.
2. Take it out of the public states with a reason:
   ``active`` -> ``PATCH /api/v2/admin/corridors/{id}`` ``rollout_state=pilot`` (``return_to_pilot``), then
   ``pilot`` -> ``rollout_state=internal`` (``return_to_internal``). Existing bookings keep running (AC38);
   the corridor leaves the public list, so no new public listings.
3. Fix the stops while ``internal``: at least two active stops, each with a meeting note or photo.
4. Return it: ``rollout_state=pilot`` (``start_pilot`` re-checks Q27/Q47), then ``activate`` if it was active.
5. Re-run the check; it must report no violations.
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.modules.geo.checks")
    sub = parser.add_subparsers(dest="check", required=True)
    sub.add_parser("q47", help="corridors in pilot/active violating Q47 (>=2 active stops with meeting evidence)")
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

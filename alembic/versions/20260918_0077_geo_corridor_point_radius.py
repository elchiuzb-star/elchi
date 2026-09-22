"""geo: the map-point radius is corridor configuration, not a constant in the code

Owner: A0a/A2 (wave 13) - follow-up to Q88.

Q88 lets a client mark a place on the map instead of picking a verified stop, and bounds it by how far that
place may sit from the confirmed road. 3 km is a sensible pilot default, but it is the wrong thing to freeze
into the application: inside Tashkent a passenger who is 3 km off the road is nowhere near it in practice,
while on a long inter-region highway a 3 km kerb-side tolerance is tight. Those are operational judgements
about a particular corridor, so they belong beside the corridor's other rollout settings and change without a
deploy.

``max_point_offset_m`` is therefore per corridor, NOT NULL with the pilot default, and bounded by a CHECK so a
careless edit cannot switch the guard off entirely (0 would accept nothing; a very large value would accept
anything and make "on route" meaningless).

Rules: additive, idempotent, single head. downgrade() is dev/test only (ADR-0016).

Revision ID: 20260918_0077
Revises: 20260918_0076
Create Date: 2026-09-18 02:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260918_0077"
down_revision: str = "20260918_0076"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Pilot default, in metres. The spec's own worked example uses a 3 km initial search radius (spec §6.4).
DEFAULT_MAX_POINT_OFFSET_M = 3_000
#: A corridor may tighten this to 100 m or widen it to 25 km; outside that it is a mistake, not a policy.
MIN_ALLOWED_M, MAX_ALLOWED_M = 100, 25_000


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE public.service_corridors ADD COLUMN IF NOT EXISTS max_point_offset_m INTEGER "
        f"NOT NULL DEFAULT {DEFAULT_MAX_POINT_OFFSET_M}"
    )
    op.execute("ALTER TABLE public.service_corridors DROP CONSTRAINT IF EXISTS ck_service_corridors_point_offset")
    op.execute(
        "ALTER TABLE public.service_corridors ADD CONSTRAINT ck_service_corridors_point_offset CHECK ("
        f"max_point_offset_m BETWEEN {MIN_ALLOWED_M} AND {MAX_ALLOWED_M})"
    )
    op.execute(
        "COMMENT ON COLUMN public.service_corridors.max_point_offset_m IS "
        "'Q88: how far from the confirmed route a marked map point may sit on this corridor, in metres. "
        "Operator configuration - a dense city and a long highway do not want the same number.'"
    )


def downgrade() -> None:
    """Dev/test only (ADR-0016): every corridor falls back to the application default."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE public.service_corridors DROP CONSTRAINT IF EXISTS ck_service_corridors_point_offset")
    op.execute("ALTER TABLE public.service_corridors DROP COLUMN IF EXISTS max_point_offset_m")

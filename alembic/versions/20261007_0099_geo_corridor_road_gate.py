"""geo corridor road gate: a public corridor needs a confirmed road, not stops (ADR-0028 phase 2, replaces Q27/Q47)

Owner: geo (ADR-0028, Q159) - integrator A0a.
Content (DATA_MODEL.md §5):
  * ``geo_assert_public_corridor_stops(corridor_id)`` (0046, called by the deferred corridor/stop triggers) now
    checks the only public-corridor condition left: a pilot/active corridor has at least one ``confirmed`` route
    version. Stop count and stop meeting evidence no longer gate anything - intermediate points are not business
    objects. The function keeps its name so the 0046 triggers keep calling it; nothing is dropped.
  * ``trg_route_versions_public_corridor_road`` - a route version insert/update re-checks its corridor (a confirmed
    road cannot be un-confirmed today, but the guard does not rely on that).

Rules: idempotent (CREATE OR REPLACE); single head; downgrade() is a dev/test tool, not a rollback (ADR-0016).

Revision ID: 20261007_0099
Revises: 20261006_0098
Create Date: 2026-10-07 09:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007_0099"
down_revision: str = "20261006_0098"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_assert_public_corridor_stops(p_corridor_id BIGINT) RETURNS void
        LANGUAGE plpgsql AS $$
        DECLARE
            state TEXT;
        BEGIN
            SELECT rollout_state INTO state FROM service_corridors WHERE id = p_corridor_id FOR NO KEY UPDATE;
            IF state IS NULL OR state NOT IN ('pilot', 'active') THEN
                RETURN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM route_versions WHERE corridor_id = p_corridor_id AND status = 'confirmed') THEN
                RAISE EXCEPTION 'service corridor %: pilot/active corridors need a confirmed road (ADR-0028)', p_corridor_id
                    USING ERRCODE = 'check_violation';
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_route_versions_public_corridor_road() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM geo_assert_public_corridor_stops(NEW.corridor_id);
            RETURN NULL;
        END
        $$
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_route_versions_public_corridor_road ON route_versions")
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_route_versions_public_corridor_road AFTER INSERT OR UPDATE ON route_versions "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION geo_route_versions_public_corridor_road()"
    )


def downgrade() -> None:
    """Dev/test only: the 0046 stop conditions again."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS trg_route_versions_public_corridor_road ON route_versions")
    op.execute("DROP FUNCTION IF EXISTS geo_route_versions_public_corridor_road()")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_assert_public_corridor_stops(p_corridor_id BIGINT) RETURNS void
        LANGUAGE plpgsql AS $$
        DECLARE
            state TEXT;
            active_count INTEGER;
            missing_count INTEGER;
        BEGIN
            SELECT rollout_state INTO state FROM service_corridors WHERE id = p_corridor_id FOR NO KEY UPDATE;
            IF state IS NULL OR state NOT IN ('pilot', 'active') THEN
                RETURN;
            END IF;
            SELECT count(*) FILTER (WHERE is_active),
                   count(*) FILTER (WHERE is_active
                                      AND (meeting_note IS NULL OR btrim(meeting_note) = '')
                                      AND meeting_photo_file_id IS NULL)
              INTO active_count, missing_count
              FROM corridor_stops WHERE corridor_id = p_corridor_id;
            IF active_count < 2 THEN
                RAISE EXCEPTION 'service corridor %: pilot/active corridors need at least 2 active stops (Q47)', p_corridor_id
                    USING ERRCODE = 'check_violation';
            END IF;
            IF missing_count > 0 THEN
                RAISE EXCEPTION 'service corridor %: every active stop needs a meeting note or photo (Q27/Q47)', p_corridor_id
                    USING ERRCODE = 'check_violation';
            END IF;
        END
        $$
        """
    )

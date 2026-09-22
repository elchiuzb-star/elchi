"""geo q48 flag gate

Owner: A2 (wave 1.7) - module `geo`.
Planned content (DATA_MODEL.md §5):
  * Q56: in production, enabling passenger_enabled / parcel_enabled / driver_listing_enabled /
    corridor_matching_enabled / tracking_enabled / card_payments_enabled is refused while the Q48 gate fails
    (feature_flag_values trigger calling the A3 gate function from 0052)
FK / object dependencies: 0052 (A3 gate function), 0033 (feature_flag_values), 0031 (platform_environment).

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / guarded DO blocks); do not change the revision id,
file name or down_revision; single head. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260915_0053
Revises: 20260915_0052
Create Date: 2026-09-15 00:53:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260915_0053"
down_revision: str = "20260915_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors app.modules.geo.service.V2_SERVICE_FLAGS.
_V2_SERVICE_FLAGS = (
    "passenger_enabled",
    "parcel_enabled",
    "driver_listing_enabled",
    "corridor_matching_enabled",
    "tracking_enabled",
    "card_payments_enabled",
)
# A3's gate (expected from 0052). Called dynamically so it may be created later; missing -> gate fails.
_A3_GATE_FUNCTION = "platform_q48_gate_passed()"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    flags = ", ".join(f"'{flag}'" for flag in _V2_SERVICE_FLAGS)

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION geo_q48_gate_passed() RETURNS boolean
        LANGUAGE plpgsql AS $$
        DECLARE
            passed BOOLEAN;
        BEGIN
            IF to_regprocedure('{_A3_GATE_FUNCTION}') IS NULL THEN
                RETURN false;  -- fail closed until A3's gate exists
            END IF;
            EXECUTE 'SELECT {_A3_GATE_FUNCTION.rstrip("()")}()' INTO passed;
            RETURN coalesce(passed, false);
        END
        $$
        """
    )

    # Q56: under the production marker (fail closed, 0043) a v2 service flag cannot be switched on while
    # the Q48 launch gate fails. Disabling, and edits of an already enabled row, stay allowed.
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION geo_feature_flag_values_q48_gate() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.enabled
               AND NEW.flag_key IN ({flags})
               AND (TG_OP = 'INSERT' OR NOT OLD.enabled)
               AND geo_production_guard_active()
               AND NOT geo_q48_gate_passed() THEN
                RAISE EXCEPTION 'feature_flag_values: enabling % in production is refused while the Q48 launch gate fails (Q56)', NEW.flag_key
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_feature_flag_values_q48_gate "
        "BEFORE INSERT OR UPDATE ON feature_flag_values "
        "FOR EACH ROW EXECUTE FUNCTION geo_feature_flag_values_q48_gate()"
    )

    # BR F1 repair path: re-check Q47 only when a corridor ENTERS a public state (or pilot -> active), so a
    # violating corridor can be moved active -> pilot -> internal to be repaired. Stop changes stay guarded
    # continuously by trg_corridor_stops_public_guard (0046).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION geo_service_corridors_public_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.rollout_state IN ('pilot', 'active')
               AND (OLD.rollout_state NOT IN ('pilot', 'active')
                    OR (OLD.rollout_state = 'pilot' AND NEW.rollout_state = 'active')) THEN
                PERFORM geo_assert_public_corridor_stops(NEW.id);
            END IF;
            RETURN NULL;
        END
        $$
        """
    )


def downgrade() -> None:
    pass

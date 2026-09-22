"""geo flag enable source guard

Owner: A2 (wave 2.1) - module `geo` (feature flags).
Planned content (DATA_MODEL.md §5, WAVE1_CARDS "Wave 2.1"):
  * Q72: feature_flag_values trigger - turning a v2 service flag ON (INSERT enabled=true or UPDATE false->true of
    passenger_enabled / parcel_enabled / driver_listing_enabled / corridor_matching_enabled / tracking_enabled /
    card_payments_enabled) is refused unless the transaction carries the application marker
    current_setting(app.contracts.enums.FLAG_CHANGE_SOURCE_SETTING, true) = FLAG_CHANGE_SOURCE_ADMIN_API
    (set with SET LOCAL by geo.service.set_flag_value only); applies in every environment;
    RAISE ... USING ERRCODE = 'insufficient_privilege', CONSTRAINT = 'flag_enable_source_refused'
  * turning flags OFF stays possible from anywhere (safe direction)
  * this migration itself must not enable any flag
FK / object dependencies: 0053 (Q56 gate trigger on the same table), 0033 (feature_flag_values).

Limitation (ADR-0008 Q72, stated honestly): the marker is an ordinary transaction setting. Anyone connected with
the app role (e.g. psql) can set it as well, and the table owner / a superuser can disable this trigger. The guard
stops accidental psql or migration enables; Q36 roles, the feature_flag_changes history and monitoring cover a
deliberate actor with full DB rights.

Trigger order: PostgreSQL fires same-event BEFORE ROW triggers in name order, so
trg_feature_flag_values_enable_source runs before _guard, _production_rules (0043), _q48_gate (0053) and
trg_feature_flag_wallet_required_guard (0041). Those triggers are unchanged.

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE / guarded DO blocks); do not change the revision id,
file name or down_revision; single head. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260915_0057
Revises: 20260915_0056
Create Date: 2026-09-15 00:57:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260915_0057"
down_revision: str = "20260915_0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies (a migration must not change when contracts evolve); tests/modules/geo compares them with
# app.contracts.enums.V2_SERVICE_FLAGS / FLAG_CHANGE_SOURCE_SETTING / FLAG_CHANGE_SOURCE_ADMIN_API.
V2_SERVICE_FLAGS = (
    "passenger_enabled",
    "parcel_enabled",
    "driver_listing_enabled",
    "corridor_matching_enabled",
    "tracking_enabled",
    "card_payments_enabled",
)
FLAG_CHANGE_SOURCE_SETTING = "elchi.flag_change_source"
FLAG_CHANGE_SOURCE_ADMIN_API = "admin_api"
CONSTRAINT_NAME = "flag_enable_source_refused"
TRIGGER_NAME = "trg_feature_flag_values_enable_source"
FUNCTION_NAME = "geo_feature_flag_values_enable_source_guard"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    flags = ", ".join(f"'{flag}'" for flag in V2_SERVICE_FLAGS)

    # Only creates a function and a trigger: no row of feature_flag_values is written here (no flag enabled).
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {FUNCTION_NAME}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.enabled
               AND NEW.flag_key IN ({flags})
               AND (TG_OP = 'INSERT' OR NOT OLD.enabled)
               AND coalesce(current_setting('{FLAG_CHANGE_SOURCE_SETTING}', true), '') <> '{FLAG_CHANGE_SOURCE_ADMIN_API}' THEN
                RAISE EXCEPTION 'feature_flag_values: turning on % is allowed only through the application flag API (Q72)', NEW.flag_key
                    USING ERRCODE = 'insufficient_privilege', CONSTRAINT = '{CONSTRAINT_NAME}';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        f"CREATE OR REPLACE TRIGGER {TRIGGER_NAME} "
        "BEFORE INSERT OR UPDATE ON feature_flag_values "
        f"FOR EACH ROW EXECUTE FUNCTION {FUNCTION_NAME}()"
    )


def downgrade() -> None:
    """Not a rollback strategy (ADR-0016)."""

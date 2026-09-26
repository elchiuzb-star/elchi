"""tracking spoofing signals: two point quality flags and one fraud signal type (Q149)

Owner: A0a (integrator) - modules `tracking` (A6) and `trust_support` (A12).
Content: widens three CHECK constraints, nothing else.
* `ck_tracking_points_quality_flags` and `ck_tracking_evidence_points_quality_flags` (0058, 0063) accept
  `zero_accuracy` (an accuracy of exactly 0 m - no phone receiver reports it; not trusted for the live marker) and
  `speed_mismatch` (the device's own speed contradicts the movement between fixes; a review signal, still trusted).
* `ck_fraud_signals_type` (0068) accepts `suspicious_location`: one tracking session kept sending spoofing-like
  points. A question for an operator, never a verdict (§10.4, §17.3) - nothing is blocked or penalised.
Existing rows already satisfy the wider constraints; no backfill. Forward only, idempotent (drop-if-exists, then add).
`downgrade()` is not a rollback strategy (ADR-0016).

Revision ID: 20260925_0095
Revises: 20260925_0094
Create Date: 2026-09-25 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260925_0095"
down_revision: str = "20260925_0094"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUALITY_FLAGS = ("low_accuracy", "mock_location", "implausible_speed", "out_of_order", "zero_accuracy", "speed_mismatch")
FRAUD_SIGNAL_TYPES = ("shared_device_accounts", "self_dealing_device", "repeated_pair_bookings", "suspicious_location")


def _array(values: Sequence[str]) -> str:
    return "ARRAY[" + ", ".join(f"'{value}'" for value in values) + "]::TEXT[]"


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in ("tracking_points", "tracking_evidence_points"):
        name = f"ck_{table}_quality_flags"
        op.execute(f"ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS {name}")
        op.execute(f"ALTER TABLE public.{table} ADD CONSTRAINT {name} CHECK (quality_flags <@ {_array(QUALITY_FLAGS)})")
    op.execute("ALTER TABLE public.fraud_signals DROP CONSTRAINT IF EXISTS ck_fraud_signals_type")
    op.execute(f"ALTER TABLE public.fraud_signals ADD CONSTRAINT ck_fraud_signals_type CHECK (signal_type IN {_in(FRAUD_SIGNAL_TYPES)})")


def downgrade() -> None:
    """Not a rollback strategy (ADR-0016)."""

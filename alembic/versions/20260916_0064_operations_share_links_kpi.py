"""operations share links kpi

Owner: A13 (wave 4) - module `operations`.
Content (DATA_MODEL.md §5, API_V2_CONTRACT §13, spec §20.2 and §20.4):
  * share_links (public_id shl_, listing_id FK listings, created_by_user_id FK users, channel, token_hash CHAR(64)
    UNIQUE - only the SHA-256 of the secret token is stored (ADR-0018), expires_at, revoked_at, opened_count,
    last_opened_at). Guard: the identity columns are immutable, a revoked link stays revoked, and the open counter
    only moves forward, so an opened link cannot be quietly rewritten.
  * kpi_daily (day, metric, corridor_id NULL = all corridors, numerator, denominator, computed_at) with
    UNIQUE NULLS NOT DISTINCT (day, metric, corridor_id) so the daily worker upserts one row per metric. Ratios are
    never stored: the reader divides, and a 0 denominator stays null instead of an invented percentage (§20.4).
FK / object dependencies: 0039 (listings), 0032 (users.public_id), 0034 (service_corridors).

Rules: idempotent (IF NOT EXISTS / CREATE OR REPLACE); do not change the revision id, file name or down_revision;
single head. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260916_0064
Revises: 20260916_0063
Create Date: 2026-09-16 01:04:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260916_0064"
down_revision: str = "20260916_0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# app.contracts.enums.ShareLinkChannel / KpiMetric
SHARE_CHANNELS = ("telegram", "generic")
KPI_METRICS = (
    "listings_published",
    "listing_to_booking",
    "offer_within_target",
    "booking_completion",
    "driver_fault_cancel",
    "repeat_client",
)
IMMUTABLE_RULE = "share_link_immutable"


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def _trigger(name: str, table: str, definition: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
    op.execute(f"CREATE TRIGGER {name} {definition}")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.share_links (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            public_id UUID NOT NULL,
            listing_id BIGINT NOT NULL CONSTRAINT fk_share_links_listing_id REFERENCES public.listings (id),
            created_by_user_id INTEGER NOT NULL CONSTRAINT fk_share_links_created_by_user_id REFERENCES public.users (id),
            channel VARCHAR(16) NOT NULL,
            token_hash CHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            opened_count INTEGER NOT NULL DEFAULT 0,
            last_opened_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_share_links_public_id UNIQUE (public_id),
            CONSTRAINT uq_share_links_token_hash UNIQUE (token_hash),
            CONSTRAINT ck_share_links_channel CHECK (channel IN {_in(SHARE_CHANNELS)}),
            CONSTRAINT ck_share_links_token_hash CHECK (token_hash ~ '^[0-9a-f]{{64}}$'),
            CONSTRAINT ck_share_links_expiry CHECK (expires_at > created_at),
            CONSTRAINT ck_share_links_opened_count CHECK (opened_count >= 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_share_links_listing_active ON public.share_links (listing_id, id) "
        "WHERE revoked_at IS NULL"
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION public.share_links_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'share_links rows are revoked, never deleted'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{IMMUTABLE_RULE}';
            END IF;
            IF (NEW.id, NEW.public_id, NEW.listing_id, NEW.created_by_user_id, NEW.channel, NEW.token_hash,
                NEW.expires_at, NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.public_id, OLD.listing_id, OLD.created_by_user_id, OLD.channel, OLD.token_hash,
                OLD.expires_at, OLD.created_at) THEN
                RAISE EXCEPTION 'share_links identity columns are immutable'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{IMMUTABLE_RULE}';
            END IF;
            IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
                RAISE EXCEPTION 'share_links: a revoked link stays revoked'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{IMMUTABLE_RULE}';
            END IF;
            IF NEW.opened_count < OLD.opened_count THEN
                RAISE EXCEPTION 'share_links: the open counter only moves forward'
                    USING ERRCODE = 'restrict_violation', CONSTRAINT = '{IMMUTABLE_RULE}';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    _trigger(
        "trg_share_links_guard",
        "public.share_links",
        "BEFORE UPDATE OR DELETE ON public.share_links FOR EACH ROW EXECUTE FUNCTION public.share_links_guard()",
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS public.kpi_daily (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            day DATE NOT NULL,
            metric VARCHAR(48) NOT NULL,
            corridor_id BIGINT CONSTRAINT fk_kpi_daily_corridor_id REFERENCES public.service_corridors (id),
            numerator BIGINT NOT NULL DEFAULT 0,
            denominator BIGINT NOT NULL DEFAULT 0,
            computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_kpi_daily_day_metric_corridor UNIQUE NULLS NOT DISTINCT (day, metric, corridor_id),
            CONSTRAINT ck_kpi_daily_metric CHECK (metric IN {_in(KPI_METRICS)}),
            -- no numerator <= denominator rule: one trip-offer listing can produce several bookings
            CONSTRAINT ck_kpi_daily_counts CHECK (numerator >= 0 AND denominator >= 0)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_kpi_daily_day_metric ON public.kpi_daily (day, metric)")


def downgrade() -> None:
    """Not a rollback strategy (ADR-0016): dropping these tables loses share-link history and KPI series."""

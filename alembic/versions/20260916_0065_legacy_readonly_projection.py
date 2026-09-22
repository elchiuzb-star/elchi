"""legacy read-only projection

Owner: A10b (wave 5) - Q4 / AC37 / spec §18.1 M4, DATA_MODEL §1.12, ADR-0006 §3-4.

Content: four **views only**, no table and no backfill. A v1 order is never copied into a v2 write table
(``listings``, ``trips``, ``bookings``, ``proposal_*``, ``ratings_v2``, ``disputes_v2``, ledger, ``wallet_*``);
v2 reads the legacy rows where they already live (AC37: rebuilding the projection twice cannot duplicate a row
or charge an old fee again, because nothing is written at all).

  * ``legacy_parcel_orders_v``   - orders + city/district names, money in minor units, ``unknown_*`` flags, engine
  * ``legacy_order_status_history_v`` - status_history + order number
  * ``legacy_ratings_v``         - ratings (never merged into ratings_v2 or reputation, DATA_MODEL §1.10)
  * ``legacy_disputes_v``        - disputes (``previous_order_status`` stays in v1, DATA_MODEL §3)

Read-only is enforced, not merely documented: every view carries INSTEAD OF INSERT/UPDATE/DELETE triggers that
raise with ``CONSTRAINT = 'legacy_object_read_only'`` (-> 409 ``LEGACY_OBJECT_READ_ONLY``, ADR-0005). The trigger
holds for every role, including the owner and a superuser; ``scripts/db_roles.py`` additionally revokes
INSERT/UPDATE/DELETE from the app role (``DEFAULT_READ_ONLY_VIEWS``), so the refusal does not depend on one layer.
A simple view over a single table would otherwise be auto-updatable and writable through the blanket DML grant.

No PII: the projection carries no phone, no exact address and no cargo photo - the v2 admin page (O8) shows a
route summary only. Money is converted from the legacy ``NUMERIC(12,2)`` so'm columns to BIGINT minor units
(1 so'm = 100 tiyin, AGENTS §6); ``legacy_calculated_fee_minor`` is the *calculated* v1 fee, never money that
was collected (spec §18.2) and never a driver debt.

Time and dimensions: v1 never stored a promised pickup/delivery window or cargo weight/volume/size, so both
flags are constant TRUE - an honest "unknown", not an invented value (ADR-0006 §3). The lifecycle timestamps of
the order are exposed as they are; migration 0066 types them (Q9).

FK / object dependencies: legacy tables only (orders, status_history, ratings, disputes, cities, districts).

Rules: idempotent (CREATE OR REPLACE VIEW, DROP TRIGGER IF EXISTS + CREATE); do not change the revision id,
file name or down_revision; single head. downgrade() is not a rollback strategy (ADR-0016, spec §18.3).

Revision ID: 20260916_0065
Revises: 20260916_0064
Create Date: 2026-09-17 06:20:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260916_0065"
down_revision: str = "20260916_0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

READ_ONLY_RULE = "legacy_object_read_only"
LEGACY_VIEWS = (
    "legacy_parcel_orders_v",
    "legacy_order_status_history_v",
    "legacy_ratings_v",
    "legacy_disputes_v",
)


def _view(name: str, body: str, comment: str) -> None:
    op.execute(f"CREATE OR REPLACE VIEW public.{name} AS\n{body}")
    escaped = comment.replace("'", "''")
    op.execute(f"COMMENT ON VIEW public.{name} IS '{escaped}'")
    for event in ("INSERT", "UPDATE", "DELETE"):
        trigger = f"trg_{name}_read_only_{event.lower()}"
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON public.{name}")
        op.execute(
            f"CREATE TRIGGER {trigger} INSTEAD OF {event} ON public.{name} "
            "FOR EACH ROW EXECUTE FUNCTION public.legacy_view_read_only()"
        )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # Any write through a legacy projection is a bug in the caller, not a recoverable state: v1 objects are
    # changed through v1 only (Q4). ERRCODE restrict_violation (23001) keeps a sane default for readers that do
    # not know the constraint name; app/contracts/db_errors.py maps the name to 409 LEGACY_OBJECT_READ_ONLY.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.legacy_view_read_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'legacy projection % is read-only through v2 (spec 18.1 M4, Q4)', TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation', CONSTRAINT = 'legacy_object_read_only';
        END;
        $$
        """
    )

    _view(
        "legacy_parcel_orders_v",
        """
        SELECT
            o.id                                  AS legacy_order_id,
            o.order_number                        AS legacy_order_number,
            o.status                              AS status,
            o.payment_status                      AS payment_status,
            o.payment_method                      AS payment_method,
            o.client_id                           AS client_user_id,
            o.assigned_driver_id                  AS assigned_driver_profile_id,
            fc.name_uz                            AS from_city_name,
            tc.name_uz                            AS to_city_name,
            fd.name_uz                            AS from_district_name,
            td.name_uz                            AS to_district_name,
            o.cargo_type                          AS cargo_type,
            CASE WHEN o.client_price IS NULL THEN NULL
                 ELSE ROUND(o.client_price * 100)::BIGINT END      AS client_price_minor,
            CASE WHEN o.final_price IS NULL THEN NULL
                 ELSE ROUND(o.final_price * 100)::BIGINT END       AS final_price_minor,
            CASE WHEN o.system_fee IS NULL THEN NULL
                 ELSE ROUND(o.system_fee * 100)::BIGINT END        AS legacy_calculated_fee_minor,
            o.system_fee_rate                     AS legacy_fee_rate,
            TRUE                                  AS unknown_time,
            TRUE                                  AS unknown_dimensions,
            o.created_at                          AS created_at,
            o.updated_at                          AS updated_at,
            o.published_at                        AS published_at,
            o.accepted_at                         AS accepted_at,
            o.picked_up_at                        AS picked_up_at,
            o.in_transit_at                       AS in_transit_at,
            o.delivered_at                        AS delivered_at,
            o.confirmed_at                        AS confirmed_at,
            o.cancelled_at                        AS cancelled_at,
            'v1'::TEXT                            AS engine
        FROM public.orders o
        JOIN public.cities fc ON fc.id = o.from_city_id
        JOIN public.cities tc ON tc.id = o.to_city_id
        LEFT JOIN public.districts fd ON fd.id = o.from_district_id
        LEFT JOIN public.districts td ON td.id = o.to_district_id
        """,
        "Q4/AC37 read-only projection of v1 orders. No phone, address or photo; money in minor units; "
        "legacy_calculated_fee_minor is the calculated v1 fee, not collected money (spec 18.2). "
        "unknown_time/unknown_dimensions are constant TRUE: v1 stored no promised window and no cargo size.",
    )

    _view(
        "legacy_order_status_history_v",
        """
        SELECT
            h.id                 AS legacy_history_id,
            h.order_id           AS legacy_order_id,
            o.order_number       AS legacy_order_number,
            h.old_status         AS old_status,
            h.new_status         AS new_status,
            h.changed_by_user_id AS changed_by_user_id,
            h.changed_by_role    AS changed_by_role,
            h.reason             AS reason,
            h.created_at         AS created_at,
            'v1'::TEXT           AS engine
        FROM public.status_history h
        JOIN public.orders o ON o.id = h.order_id
        """,
        "Q4 read-only projection of v1 order status history.",
    )

    _view(
        "legacy_ratings_v",
        """
        SELECT
            r.id           AS legacy_rating_id,
            r.order_id     AS legacy_order_id,
            o.order_number AS legacy_order_number,
            r.client_id    AS author_user_id,
            r.driver_id    AS subject_driver_profile_id,
            r.rating       AS stars,
            r.comment      AS comment,
            r.created_at   AS created_at,
            'v1'::TEXT     AS engine
        FROM public.ratings r
        JOIN public.orders o ON o.id = r.order_id
        """,
        "Q4 read-only projection of v1 ratings. Legacy stars are never merged into ratings_v2 or into a v2 "
        "reputation snapshot (DATA_MODEL 1.10, spec 8.2: no invented rating for a new driver).",
    )

    _view(
        "legacy_disputes_v",
        """
        SELECT
            d.id                 AS legacy_dispute_id,
            d.order_id           AS legacy_order_id,
            o.order_number       AS legacy_order_number,
            d.opened_by_user_id  AS opened_by_user_id,
            d.reason             AS reason,
            d.comment            AS comment,
            d.status             AS status,
            d.resolution         AS resolution,
            d.resolved_by        AS resolved_by_user_id,
            d.resolved_at        AS resolved_at,
            d.created_at         AS created_at,
            d.updated_at         AS updated_at,
            'v1'::TEXT           AS engine
        FROM public.disputes d
        JOIN public.orders o ON o.id = d.order_id
        """,
        "Q4 read-only projection of v1 disputes. previous_order_status stays in v1 (DATA_MODEL 3).",
    )


def downgrade() -> None:
    """Dev/test only (ADR-0016): dropping a view removes no data."""
    if op.get_bind().dialect.name != "postgresql":
        return
    for name in LEGACY_VIEWS:
        op.execute(f"DROP VIEW IF EXISTS public.{name}")
    op.execute("DROP FUNCTION IF EXISTS public.legacy_view_read_only()")

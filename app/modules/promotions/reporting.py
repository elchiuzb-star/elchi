"""Operational promo report (referral stage 6, A6.2, ADR-0023 §20) - real rows only, never simulator output.

Read-only: nothing here inserts, updates, locks or emits an event; the caller's transaction is rolled back by the
read path. Money is UZS minor units. Two kinds of numbers are kept apart and labelled:

* **state** (``budgets``, ``outstanding_minor``, ``pending_review_minor``) - as of ``generated_at``;
* **flows** (enrollments, grants, spends, promo bookings) - inside ``[start, end)`` (UTC day bounds, at most 366 days),
  each with the timestamp it is counted by (``period_basis``).

A metric that does not belong to a grouping (e.g. an enrollment count by corridor: enrollments have no corridor) is
``None`` - "not applicable", never 0. No user id, name, phone or code is returned; groups are services, corridor and
campaign public ids, campaign version numbers and enrollment weeks.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.contracts.errors import DomainError, ErrorCode
from app.contracts.ids import PublicIdPrefix, format_public_id

MAX_PERIOD_DAYS = 366
STATEMENT_TIMEOUT_MS = 10_000  # the report is aggregates only; a slow plan fails instead of loading the database
GROUPINGS = ("service", "corridor", "campaign_version", "cohort")
NO_ENROLLMENT = "no_enrollment"  # an obligation not created by an enrollment (never expected in production)
COHORT_BASIS = "enrollment_week_asia_tashkent"  # the cohort anchor: the enrollment, never activation or grant
PERIOD_BASIS = {
    "enrollments": "promo_enrollments.enrolled_at",
    "promised_minor": "promo_obligations.created_at",
    "granted_passenger_bonus_minor": "promo_lots.created_at (grant)",
    "granted_driver_credit_minor": "promo_lots.created_at (grant)",
    "spent_passenger_bonus_minor": "promo_redemptions.settled_at (consumed)",
    "spent_driver_credit_minor": "promo_redemptions.settled_at (consumed)",
    "expired_minor": "promo_lots.expires_at (status expired)",
    "promo_bookings": "promo_booking_terms.created_at of the first terms row",
    "net_commission_captured_minor": "bookings of the period; capture state as of generated_at",
}
# which metrics a grouping can carry (the rest are None = not applicable)
_APPLIES = {
    "service": {"enrollments", "promised", "granted", "spent", "expired", "bookings", "state"},
    "corridor": {"spent", "bookings"},
    "campaign_version": {"enrollments", "promised", "granted", "spent", "expired", "state"},
    "cohort": {"enrollments", "promised", "granted", "spent", "expired", "state"},
}


def day_bounds(from_: date, to: date) -> tuple[datetime, datetime]:
    if to < from_ or (to - from_) > timedelta(days=MAX_PERIOD_DAYS - 1):
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "to", "max_days": MAX_PERIOD_DAYS})
    return datetime.combine(from_, time.min, tzinfo=UTC), datetime.combine(to + timedelta(days=1), time.min, tzinfo=UTC)


def _campaign_key(public_id: uuid.UUID) -> str:
    return format_public_id(PublicIdPrefix.PROMO_CAMPAIGN, public_id)


# --- key expressions per grouping ------------------------------------------------------------------------------------

# every flow query joins what its grouping needs (c/v campaign+version, e enrollment, sc corridor)
_KEYS = {
    "service": "{svc}",
    "campaign_version": "c.public_id::text || '/v' || v.version_no",
    "cohort": "to_char(date_trunc('week', e.enrolled_at AT TIME ZONE 'Asia/Tashkent'), 'YYYY-MM-DD')",
    "corridor": "sc.public_id::text",
}


def _key(grouping: str, svc: str) -> str:
    return _KEYS[grouping].format(svc=svc)


def build_report(session: Session, *, group_by: str, start: datetime, end: datetime, now: datetime) -> dict[str, Any]:
    if group_by not in GROUPINGS:
        raise DomainError(ErrorCode.VALIDATION_ERROR, details={"field": "group_by", "allowed": list(GROUPINGS)})
    if session.get_bind().dialect.name != "postgresql":
        raise DomainError(ErrorCode.SERVICE_UNAVAILABLE, details={"reason": "postgresql_required"})
    params = {"start": start, "end": end, "now": now}
    session.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'"))  # bounded computation time
    applies = _APPLIES[group_by]
    rows: dict[str, dict[str, int | None]] = defaultdict(dict)

    def put(sql: str, *names: str) -> None:
        for record in session.execute(text(sql), params):
            key = NO_ENROLLMENT if record[0] is None else str(record[0])  # e.g. a cohort row without an enrollment
            for index, name in enumerate(names, start=1):
                rows[key][name] = int(record[index] or 0)

    # cohort rows: only enrollments of the period's weeks; other groupings: state is all-time as of now
    cohort_only = "AND e.enrolled_at >= :start AND e.enrolled_at < :end" if group_by == "cohort" else ""
    obligation_join = ("JOIN promo_campaign_versions v ON v.id = o.campaign_version_id "
                       "JOIN promo_campaigns c ON c.id = o.campaign_id "
                       "LEFT JOIN promo_enrollments e ON e.id = o.enrollment_id")
    if "enrollments" in applies:
        put(f"""SELECT {_key(group_by, 'e.service_type')}, count(*),
                       count(*) FILTER (WHERE e.status = 'granted'), count(*) FILTER (WHERE e.status = 'promised'),
                       count(*) FILTER (WHERE e.status = 'released')
                  FROM promo_enrollments e
                  JOIN promo_campaign_versions v ON v.id = e.campaign_version_id
                  JOIN promo_campaigns c ON c.id = e.campaign_id
                 WHERE e.enrolled_at >= :start AND e.enrolled_at < :end GROUP BY 1""",
            "enrollments", "enrollments_granted", "enrollments_open", "enrollments_released")
    if "promised" in applies:
        put(f"""SELECT {_key(group_by, 'o.service_type')}, sum(o.amount_minor)
                  FROM promo_obligations o {obligation_join}
                 WHERE o.created_at >= :start AND o.created_at < :end GROUP BY 1""", "promised_minor")
    if "granted" in applies:
        put(f"""SELECT {_key(group_by, 'l.service_type')}, sum(l.amount_minor) FILTER (WHERE l.instrument = 'passenger_bonus'),
                       sum(l.amount_minor) FILTER (WHERE l.instrument = 'driver_credit')
                  FROM promo_lots l JOIN promo_obligations o ON o.id = l.obligation_id {obligation_join}
                 WHERE l.created_at >= :start AND l.created_at < :end GROUP BY 1""",
            "granted_passenger_bonus_minor", "granted_driver_credit_minor")
    if "expired" in applies:
        put(f"""SELECT {_key(group_by, 'l.service_type')}, sum(l.expired_minor)
                  FROM promo_lots l JOIN promo_obligations o ON o.id = l.obligation_id {obligation_join}
                 WHERE l.status = 'expired' AND l.expires_at >= :start AND l.expires_at < :end GROUP BY 1""",
            "expired_minor")
    if "spent" in applies:
        corridor_join = ("JOIN bookings b ON b.id = r.booking_id JOIN service_corridors sc ON sc.id = b.corridor_id"
                         if group_by == "corridor" else "")
        put(f"""SELECT {_key(group_by, 'l.service_type')},
                       sum(r.amount_minor) FILTER (WHERE l.instrument = 'passenger_bonus'),
                       sum(r.amount_minor) FILTER (WHERE l.instrument = 'driver_credit')
                  FROM promo_redemptions r JOIN promo_lots l ON l.id = r.lot_id
                  JOIN promo_obligations o ON o.id = l.obligation_id {obligation_join} {corridor_join}
                 WHERE r.status = 'consumed' AND r.settled_at >= :start AND r.settled_at < :end GROUP BY 1""",
            "spent_passenger_bonus_minor", "spent_driver_credit_minor")
    if "bookings" in applies:
        put(f"""WITH first_terms AS (
                    SELECT booking_id, min(created_at) AS accepted_at FROM promo_booking_terms GROUP BY booking_id),
                     last_terms AS (
                    SELECT DISTINCT ON (booking_id) * FROM promo_booking_terms ORDER BY booking_id, seq DESC)
                SELECT {_key(group_by, 'b.service_type')}, count(*), sum(t.base_commission_minor),
                       sum(t.passenger_bonus_minor), sum(t.driver_credit_minor), sum(t.net_commission_minor),
                       sum(COALESCE(h.captured, 0)), sum(COALESCE(h.reversed, 0))
                  FROM first_terms f JOIN last_terms t ON t.booking_id = f.booking_id
                  JOIN bookings b ON b.id = f.booking_id JOIN service_corridors sc ON sc.id = b.corridor_id
                  LEFT JOIN (SELECT booking_id, sum(captured_minor) AS captured, sum(reversed_minor) AS reversed
                               FROM wallet_holds WHERE status = 'captured' GROUP BY booking_id) h ON h.booking_id = b.id
                 WHERE f.accepted_at >= :start AND f.accepted_at < :end
                   AND t.passenger_bonus_minor + t.driver_credit_minor > 0 GROUP BY 1""",
            "promo_bookings", "base_commission_minor", "passenger_bonus_minor", "driver_credit_minor",
            "net_commission_agreed_minor", "net_commission_captured_minor", "commission_reversed_minor")
    if "state" in applies:  # as of now, whatever the period
        put(f"""SELECT {_key(group_by, 'o.service_type')},
                       sum(o.amount_minor) FILTER (WHERE o.status = 'promised'),
                       sum(o.amount_minor) FILTER (WHERE o.status = 'promised' AND EXISTS (
                           SELECT 1 FROM promo_reviews rv WHERE rv.enrollment_id = o.enrollment_id
                              AND rv.status IN ('open', 'under_review')))
                  FROM promo_obligations o {obligation_join}
                 WHERE true {cohort_only} GROUP BY 1""", "promised_open_minor", "promised_in_review_minor")
        put(f"""SELECT {_key(group_by, 'l.service_type')},
                       sum(l.amount_minor - l.consumed_minor - l.expired_minor - l.reversed_minor)
                           FILTER (WHERE l.status IN ('available', 'pending_review')),
                       sum(l.reserved_minor),
                       sum(l.amount_minor - l.reserved_minor - l.consumed_minor - l.expired_minor - l.reversed_minor)
                           FILTER (WHERE l.status = 'pending_review')
                  FROM promo_lots l JOIN promo_obligations o ON o.id = l.obligation_id {obligation_join}
                 WHERE true {cohort_only} GROUP BY 1""",
            "granted_unspent_minor", "reserved_on_bookings_minor", "lots_pending_review_minor")

    out_rows = []
    all_metrics = ("enrollments", "enrollments_granted", "enrollments_open", "enrollments_released", "promised_minor",
                   "granted_passenger_bonus_minor", "granted_driver_credit_minor", "spent_passenger_bonus_minor",
                   "spent_driver_credit_minor", "expired_minor", "promo_bookings", "base_commission_minor",
                   "passenger_bonus_minor", "driver_credit_minor", "net_commission_agreed_minor",
                   "net_commission_captured_minor", "commission_reversed_minor", "promised_open_minor",
                   "promised_in_review_minor", "granted_unspent_minor", "reserved_on_bookings_minor",
                   "lots_pending_review_minor")
    group_of = {
        "enrollments": "enrollments", "enrollments_granted": "enrollments", "enrollments_open": "enrollments",
        "enrollments_released": "enrollments", "promised_minor": "promised", "granted_passenger_bonus_minor": "granted",
        "granted_driver_credit_minor": "granted", "spent_passenger_bonus_minor": "spent",
        "spent_driver_credit_minor": "spent", "expired_minor": "expired",
        "promised_open_minor": "state", "promised_in_review_minor": "state", "granted_unspent_minor": "state",
        "reserved_on_bookings_minor": "state", "lots_pending_review_minor": "state",
    }
    for key in sorted(rows):
        values = {m: (rows[key].get(m, 0) if group_of.get(m, "bookings") in applies else None) for m in all_metrics}
        state_ok = "state" in applies
        values["outstanding_liability_minor"] = (values["promised_open_minor"] + values["granted_unspent_minor"]) if state_ok else None
        values["pending_review_minor"] = (values["promised_in_review_minor"] + values["lots_pending_review_minor"]) if state_ok else None
        if values["net_commission_captured_minor"] is not None:
            values["net_commission_kept_minor"] = values["net_commission_captured_minor"] - values["commission_reversed_minor"]
        else:
            values["net_commission_kept_minor"] = None
        row: dict[str, Any] = {"key": _display_key(group_by, key), "values": values}
        if group_by == "cohort" and key != NO_ENROLLMENT:
            start_day = date.fromisoformat(key)
            observed = (now.date() - start_day).days
            row["cohort"] = {"anchor": COHORT_BASIS, "week_start": start_day.isoformat(), "observed_days": observed,
                             # every enrollment of the week has had N days only after the week's last day + N
                             "matured_d30": observed >= 30 + 6, "matured_d60": observed >= 60 + 6}
        out_rows.append(row)
    return {"data_source": "operational", "currency": "UZS", "amount_unit": "minor", "group_by": group_by,
            "generated_at": now, "period": {"start_at": start, "end_at": end, "end_exclusive": True,
                                            "day_bounds": "UTC"},
            "period_basis": PERIOD_BASIS, "rows": out_rows, "budgets": _budgets(session, now)}


def _display_key(group_by: str, key: str) -> str:
    if key == NO_ENROLLMENT:
        return key
    if group_by == "corridor":
        return format_public_id(PublicIdPrefix.CORRIDOR, uuid.UUID(key))
    if group_by == "campaign_version":
        campaign, _, version = key.partition("/")
        return f"{_campaign_key(uuid.UUID(campaign))}/{version}"
    return key


def _budgets(session: Session, now: datetime) -> list[dict[str, Any]]:
    """Every campaign's budget state as of now: limit, commitment, funding and what is waiting for a person."""
    out = []
    for r in session.execute(text("""
        SELECT c.public_id, c.service_type, c.kind, c.status,
               COALESCE(b.allocated_minor, 0) AS allocated, COALESCE(b.promised_minor, 0) AS promised,
               COALESCE(b.granted_minor, 0) AS granted, COALESCE(b.consumed_minor, 0) AS consumed,
               COALESCE(b.released_minor, 0) AS released,
               COALESCE(l.reserved, 0) AS reserved, COALESCE(l.pending, 0) AS lots_pending,
               COALESCE(o.in_review, 0) AS promised_in_review,
               public.promo_pending_reinstatements(c.id) AS pending_reinstatements
          FROM promo_campaigns c
          LEFT JOIN promo_budgets b ON b.campaign_id = c.id
          LEFT JOIN (SELECT campaign_id, sum(reserved_minor) AS reserved,
                            sum(amount_minor - reserved_minor - consumed_minor - expired_minor - reversed_minor)
                                FILTER (WHERE status = 'pending_review') AS pending
                       FROM promo_lots GROUP BY campaign_id) l ON l.campaign_id = c.id
          LEFT JOIN (SELECT ob.campaign_id, sum(ob.amount_minor) AS in_review FROM promo_obligations ob
                      WHERE ob.status = 'promised' AND EXISTS (
                            SELECT 1 FROM promo_reviews rv WHERE rv.enrollment_id = ob.enrollment_id
                               AND rv.status IN ('open', 'under_review'))
                      GROUP BY ob.campaign_id) o ON o.campaign_id = c.id
         ORDER BY c.id""")):
        committed = r.promised + r.granted + r.consumed
        shortfall = max(committed - r.allocated, 0)
        alerts = ["budget_shortfall"] if shortfall else []
        out.append({
            "campaign_id": _campaign_key(r.public_id), "service_type": r.service_type, "kind": r.kind, "status": r.status,
            "allocated_minor": r.allocated, "promised_minor": r.promised, "granted_unspent_minor": r.granted,
            "reserved_on_bookings_minor": r.reserved, "consumed_minor": r.consumed, "released_minor": r.released,
            "committed_minor": committed, "outstanding_liability_minor": r.promised + r.granted,
            "shortfall_minor": shortfall, "funded_commitment_minor": committed - shortfall,
            "available_for_new_minor": max(r.allocated - committed, 0),
            "pending_reinstatements_minor": r.pending_reinstatements,
            # G14: B >= S + L; L = promised + granted (incl. reserved) + approved reinstatements waiting for room
            "reducible_minor": max(r.allocated - committed - r.pending_reinstatements, 0),
            "pending_review_minor": r.lots_pending + r.promised_in_review, "alerts": alerts,
        })
    return out

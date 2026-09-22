"""Commission policy rules on PostgreSQL (Q1, Q2, Q19, K5, AC43)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.enums import CommissionPolicyKind
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.timeutil import utc_now
from app.modules.wallet import service
from tests.pg.wallet.conftest import ADMIN_CAPS, FINANCE_CAPS, OPERATOR_CAPS, SUPER_CAPS

pytestmark = pytest.mark.pg


def _create(s, actor, **overrides):
    now = utc_now()
    args = dict(actor_user_id=actor, actor_capabilities=SUPER_CAPS, kind="campaign", corridor_id=None, service_type=None,
                fee_bps=0, effective_from=now + timedelta(hours=1), effective_to=now + timedelta(hours=2),
                campaign_name="pilot launch", reason="pilot")
    args.update(overrides)
    return service.create_policy(s, **args)


def test_seeded_global_standard_resolves(pg_db):
    with pg_db.session() as s:
        quote = service.quote_fee(s, corridor_id=None, service_type="passenger", total_minor=40_000_000)
        assert (quote.fee_bps, quote.commission_minor, quote.net_minor) == (1500, 6_000_000, 34_000_000)
        assert quote.policy_kind is CommissionPolicyKind.STANDARD and quote.policy_public_id.startswith("cmp_")


def test_q1_standard_zero_bps_and_open_campaign_rejected(pg_db, people):
    with pg_db.session() as s:
        for overrides in (dict(kind="standard", fee_bps=0, effective_to=None, campaign_name=None),
                          dict(effective_to=None)):
            with pytest.raises(DomainError) as exc:
                _create(s, people["super"], **overrides)
            assert exc.value.code is ErrorCode.VALIDATION_ERROR
    for sql in (
        "INSERT INTO commission_policies (public_id, kind, fee_bps, effective_from, reason) VALUES (:p, 'standard', 0, now() + interval '1 day', 'x')",
        "INSERT INTO commission_policies (public_id, kind, fee_bps, effective_from, campaign_name, reason) VALUES (:p, 'campaign', 0, now() + interval '1 day', 'c', 'x')",
    ):
        with pytest.raises(DBAPIError, match="check constraint"):
            with pg_db.engine.begin() as conn:
                conn.execute(text(sql), {"p": uuid.uuid4()})


def test_overlap_rejected_by_service_and_exclusion_constraint(pg_db, people):
    with pg_db.session() as s:
        first = _create(s, people["super"])
        s.commit()
        with pytest.raises(DomainError) as exc:
            _create(s, people["super"], effective_from=first.effective_from + timedelta(minutes=30),
                    effective_to=first.effective_to + timedelta(hours=1))
        assert exc.value.code is ErrorCode.COMMISSION_POLICY_OVERLAP
    with pytest.raises(DBAPIError) as db_exc:
        with pg_db.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO commission_policies (public_id, kind, fee_bps, effective_from, effective_to, campaign_name, reason) "
                "SELECT :p, 'campaign', 500, effective_from + interval '10 minutes', effective_to, 'dup', 'x' "
                "FROM commission_policies WHERE kind = 'campaign'"), {"p": uuid.uuid4()})
    assert db_exc.value.orig.sqlstate == "23P01"


def test_backdating_rejected_by_service_and_trigger(pg_db, people):
    with pg_db.session() as s:
        with pytest.raises(DomainError) as exc:
            _create(s, people["super"], effective_from=utc_now() - timedelta(hours=1))
        assert exc.value.code is ErrorCode.COMMISSION_POLICY_RETROACTIVE
    with pytest.raises(DBAPIError, match="retroactive"):
        with pg_db.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO commission_policies (public_id, kind, fee_bps, effective_from, effective_to, campaign_name, reason) "
                "VALUES (:p, 'campaign', 0, now() - interval '1 hour', now() + interval '1 hour', 'c', 'x')"), {"p": uuid.uuid4()})


def test_q2_only_super_admin_manages_policies(pg_db, people):
    with pg_db.session() as s:
        for caps in (ADMIN_CAPS, OPERATOR_CAPS, FINANCE_CAPS):
            with pytest.raises(DomainError) as exc:
                _create(s, people["admin"], actor_capabilities=caps)
            assert exc.value.code is ErrorCode.FORBIDDEN
        policy = _create(s, people["super"])
        with pytest.raises(DomainError) as exc:
            service.end_policy(s, actor_user_id=people["admin"], actor_capabilities=ADMIN_CAPS, policy_id=policy.id,
                               expected_version=1, effective_to=policy.effective_from + timedelta(minutes=10), reason="x")
        assert exc.value.code is ErrorCode.FORBIDDEN


def test_q19_resolution_precedence_campaign_then_specific_scope(pg_db, people):
    now = utc_now()
    with pg_db.session() as s:
        service.create_policy(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, kind="standard",
                              corridor_id=None, service_type="parcel", fee_bps=1200, effective_from=now + timedelta(hours=1),
                              effective_to=None, campaign_name=None, reason="parcel rate")
        _create(s, people["super"], effective_from=now + timedelta(hours=2), effective_to=now + timedelta(hours=3))
        s.commit()

        def bps(service_type, hours):
            return service.quote_fee(s, corridor_id=None, service_type=service_type, total_minor=1_000_000,
                                     at=now + timedelta(hours=hours)).fee_bps

        assert bps("parcel", 1.5) == 1200      # service scope beats global standard
        assert bps("passenger", 1.5) == 1500   # global standard
        assert bps("parcel", 2.5) == 0         # any campaign beats standard (Q19)
        assert bps("passenger", 2.5) == 0
        assert bps("parcel", 4) == 1200        # campaign ended
        # AC43: a quote taken now keeps its policy/bps even though a campaign starts later.
        assert service.quote_fee(s, corridor_id=None, service_type="parcel", total_minor=1_000_000).fee_bps == 1500


def test_end_policy_once_future_only_and_rows_immutable(pg_db, people):
    with pg_db.session() as s:
        policy = _create(s, people["super"], effective_to=utc_now() + timedelta(days=10))
        ended = service.end_policy(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, policy_id=policy.id,
                                   expected_version=1, effective_to=utc_now() + timedelta(days=1), reason="stop early")
        s.commit()
        assert ended.version == 2 and ended.ended_by == people["super"]
        with pytest.raises(DomainError) as exc:
            service.end_policy(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, policy_id=policy.id,
                               expected_version=2, effective_to=utc_now() + timedelta(hours=5), reason="again")
        assert exc.value.code is ErrorCode.INVALID_STATE_TRANSITION
        s.rollback()
        other = _create(s, people["super"], effective_from=utc_now() + timedelta(days=20),
                        effective_to=utc_now() + timedelta(days=21))
        with pytest.raises(DomainError) as exc:
            service.end_policy(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, policy_id=other.id,
                               expected_version=1, effective_to=utc_now() - timedelta(hours=1), reason="past")
        assert exc.value.code is ErrorCode.COMMISSION_POLICY_RETROACTIVE
    for sql in ("UPDATE commission_policies SET fee_bps = 1", "DELETE FROM commission_policies"):
        with pytest.raises(DBAPIError, match="immutable"):
            with pg_db.engine.begin() as conn:
                conn.execute(text(sql))


def test_v1_replace_global_standard_ends_current_and_starts_new(pg_db, people):
    with pg_db.session() as s:
        new = service.replace_global_standard(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                              fee_bps=1250, reason="v1 patch")
        s.commit()
        rows = s.execute(text("SELECT fee_bps, effective_to IS NULL, ended_by FROM commission_policies "
                              "WHERE kind='standard' AND scope_key='*:*' ORDER BY id")).all()
        assert [tuple(r) for r in rows] == [(1500, False, people["super"]), (1250, True, None)]
        assert service.current_global_standard(s).id == new.id
        with pytest.raises(DomainError) as exc:
            service.replace_global_standard(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                            fee_bps=0, reason="zero")
        assert exc.value.code is ErrorCode.VALIDATION_ERROR
        with pytest.raises(DomainError):
            service.replace_global_standard(s, actor_user_id=people["admin"], actor_capabilities=ADMIN_CAPS,
                                            fee_bps=1000, reason="admin")


# --- wave 1.5 ---------------------------------------------------------------------------------------------


def test_br6_global_standard_cannot_end_without_successor(pg_db, people):
    with pg_db.session() as s:
        seed = service.current_global_standard(s)
        with pytest.raises(DomainError) as exc:
            service.end_policy(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS, policy_id=seed.id,
                               expected_version=seed.version, effective_to=utc_now() + timedelta(hours=1), reason="stop")
        assert exc.value.code is ErrorCode.INVALID_STATE_TRANSITION
        assert exc.value.details["reason"] == "global_standard_requires_successor"
    with pytest.raises(DBAPIError, match="without a successor"):
        with pg_db.engine.begin() as conn:
            conn.execute(text(
                "UPDATE commission_policies SET effective_to = now() + interval '1 hour', ended_by = :u, "
                "ended_reason = 'raw', version = version + 1 WHERE kind = 'standard' AND scope_key = '*:*'"),
                {"u": people["super"]})


def test_br6_scheduled_replace_switches_global_standard_atomically(pg_db, people):
    switch = utc_now() + timedelta(hours=2)
    with pg_db.session() as s:
        new = service.replace_global_standard(s, actor_user_id=people["super"], actor_capabilities=SUPER_CAPS,
                                              fee_bps=1300, reason="scheduled change", effective_from=switch)
        s.commit()
        assert abs((new.effective_from - switch).total_seconds()) < 1

        def bps(at):
            return service.quote_fee(s, corridor_id=None, service_type="passenger", total_minor=1_000_000, at=at).fee_bps

        assert bps(switch - timedelta(minutes=1)) == 1500
        assert bps(switch + timedelta(minutes=1)) == 1300
        assert service.assert_production_invariants(s).ok


def test_br7_small_clock_skew_is_clamped_and_old_values_rejected(pg_db, people):
    with pg_db.session() as s:
        requested = utc_now() - timedelta(seconds=30)
        policy = _create(s, people["super"], effective_from=requested, effective_to=utc_now() + timedelta(hours=1))
        s.commit()
        assert policy.effective_from > requested + timedelta(seconds=25)
        with pytest.raises(DomainError) as exc:
            _create(s, people["super"], service_type="parcel", effective_from=utc_now() - timedelta(minutes=2))
        assert exc.value.code is ErrorCode.COMMISSION_POLICY_RETROACTIVE
    with pg_db.engine.begin() as conn:
        clamped = conn.execute(text(
            "INSERT INTO commission_policies (public_id, kind, scope_service_type, fee_bps, effective_from, effective_to, "
            "campaign_name, reason) VALUES (:p, 'campaign', 'parcel', 0, now() - interval '30 seconds', "
            "now() + interval '5 hours', 'raw', 'x') RETURNING effective_from >= now()"), {"p": uuid.uuid4()}).scalar()
    assert clamped is True
    with pytest.raises(DBAPIError, match="retroactive"):
        with pg_db.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO commission_policies (public_id, kind, scope_service_type, fee_bps, effective_from, "
                "effective_to, campaign_name, reason) VALUES (:p, 'campaign', 'passenger', 0, now() - interval '2 minutes', "
                "now() + interval '5 hours', 'raw', 'x')"), {"p": uuid.uuid4()})

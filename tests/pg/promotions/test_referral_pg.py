"""Referral codes, attribution and enrollment on PostgreSQL (referral stage 2, ADR-0023, Q106/Q108/Q117-Q119).

Real transactions, unique constraints and parallel connections. SYNTHETIC people, codes and amounts only.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.contracts.enums import PromoCampaignKind
from app.contracts.errors import DomainError, ErrorCode
from app.contracts.promo import IdentityRetentionPolicy
from app.contracts.timeutil import utc_now
from app.modules.promotions import identity as identity_service
from app.modules.promotions import referral, service
from tests.pg.harness import run_concurrently
from tests.pg.identity.a1_world import add_user, run_in_thread, wait_for_lock_waiters
from tests.pg.promotions.conftest import COMMITMENT, SUPER_CAPS, synthetic_terms
from tests.pg.promotions.referral_world import KEYS, Ref, enable_promotions, new_phone, open_booking_for

pytestmark = pytest.mark.pg


@pytest.fixture
def ref(promo) -> Ref:  # noqa: ANN001
    enable_promotions(promo.pg_db)
    return Ref(promo)


def _code(exc_info) -> ErrorCode:  # noqa: ANN001
    return exc_info.value.code


def _err(result) -> ErrorCode | None:  # noqa: ANN001
    return result.error.code if isinstance(result.error, DomainError) else None


# --- codes (Q117) ---------------------------------------------------------------------------------------------------


def test_code_is_random_unique_and_retried_on_collision(ref) -> None:  # noqa: ANN001
    a, b = ref.client(), ref.client()
    same = iter([0] * 8 + [0] * 8 + [1] * 8)  # owner b first draws owner a's code, then a fresh one
    with ref.pg_db.session() as s:
        first = referral.issue_referral_code(s, owner_user_id=a, randbelow=lambda n: next(same))
        second = referral.issue_referral_code(s, owner_user_id=b, randbelow=lambda n: next(same))
        s.commit()
        assert first.code != second.code
        assert referral.issue_referral_code(s, owner_user_id=a).id == first.id  # idempotent per owner
    with pytest.raises(DBAPIError) as info:  # the DB, not only the service, keeps codes unique
        with ref.pg_db.engine.begin() as conn:
            conn.execute(text("INSERT INTO referral_codes (public_id, code, owner_user_id) VALUES (gen_random_uuid(), :c, :o)"),
                         {"c": first.code, "o": ref.client()})
    assert info.value.orig.diag.constraint_name == "uq_referral_codes_code"


def test_code_owner_never_changes_and_codes_are_not_derived_from_the_owner(ref) -> None:  # noqa: ANN001
    owner = ref.client()
    code = ref.code(owner)
    with ref.pg_db.engine.connect() as conn:
        phone = conn.execute(text("SELECT phone FROM users WHERE id = :u"), {"u": owner}).scalar_one()
    assert code not in phone and str(owner) not in code
    with pytest.raises(DBAPIError) as info:
        with ref.pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE referral_codes SET owner_user_id = :o WHERE code = :c"), {"o": ref.client(), "c": code})
    assert info.value.orig.diag.constraint_name == "promo_invalid_transition"


def test_code_check_reveals_nothing_about_the_owner(ref) -> None:  # noqa: ANN001
    owner = ref.client()
    code = ref.code(owner)
    with ref.pg_db.session() as s:
        result = referral.check_code(s, code)
        assert result == referral.CodeCheck(valid=True)
        assert set(result.__slots__) == {"valid"}  # no owner id, name or phone - by construction
        assert referral.check_code(s, "22222222") == referral.CodeCheck(valid=False)
    with ref.pg_db.engine.begin() as conn:  # blocked / deleted owner: same answer as an unknown code
        conn.execute(text("UPDATE users SET status = 'blocked' WHERE id = :u"), {"u": owner})
    with ref.pg_db.session() as s:
        assert referral.check_code(s, code) == referral.CodeCheck(valid=False)


def test_revoking_a_code_keeps_earlier_attributions_and_promises(ref) -> None:  # noqa: ANN001
    campaign = ref.campaign()
    referrer, referee = ref.client(), ref.client()
    code = ref.code(referrer)
    attribution = ref.attribute(referee, code)
    enrollment = ref.enroll(referee, attribution, campaign)
    with ref.pg_db.session() as s:
        code_id = s.execute(text("SELECT id FROM referral_codes WHERE code = :c"), {"c": code}).scalar_one()
        new = referral.revoke_referral_code(s, code_id=code_id, actor_user_id=referrer, reason="owner asked")
        s.commit()
        assert new is not None and new.code != code
        assert referral.check_code(s, code).valid is False
    assert ref.count("referral_attributions", "id = :a AND referral_code_id = :c AND referrer_user_id = :r",
                     a=attribution, c=code_id, r=referrer) == 1
    assert ref.count("promo_obligations", "enrollment_id = :e AND status = 'promised'", e=enrollment) == 2


# --- attribution (Q106, Q117) ------------------------------------------------------------------------------------


def test_two_parallel_codes_attach_exactly_one(ref) -> None:  # noqa: ANN001
    referee = ref.client()
    codes = [ref.code(ref.client()), ref.code(ref.client())]

    def attach(index: int, session) -> int:  # noqa: ANN001
        row = referral.attribute(session, referee_user_id=referee, raw_code=codes[index], audience_role="client",
                                 idempotency_key=f"k{index}")
        session.commit()
        return row.referrer_user_id

    report = run_concurrently(2, attach, engine=ref.pg_db.engine)
    assert len(report.successes) == 1
    assert [_err(r) for r in report.failures] == [ErrorCode.REFERRAL_ALREADY_ATTRIBUTED]
    assert ref.count("referral_attributions", "referee_user_id = :u", u=referee) == 1
    # a later link or a retry never replaces it
    with pytest.raises(DomainError) as exc:
        ref.attribute(referee, codes[1 - report.successes[0].index])
    assert _code(exc) is ErrorCode.REFERRAL_ALREADY_ATTRIBUTED


def test_72_hour_window_uses_the_server_clock(ref) -> None:  # noqa: ANN001
    code = ref.code(ref.client())
    inside = ref.client(hours_ago=71.9)
    ref.attribute(inside, code)
    outside = ref.client(hours_ago=72.01)
    with pytest.raises(DomainError) as exc:
        ref.attribute(outside, code)
    assert _code(exc) is ErrorCode.REFERRAL_WINDOW_CLOSED
    unverified = ref.client(verified=False)
    with pytest.raises(DomainError) as exc:
        ref.attribute(unverified, code)
    assert _code(exc) is ErrorCode.REFERRAL_WINDOW_CLOSED
    with ref.pg_db.engine.connect() as conn:
        row = conn.execute(text("SELECT window_ends_at - window_started_at FROM referral_attributions "
                                "WHERE referee_user_id = :u"), {"u": inside}).scalar_one()
    assert row == timedelta(hours=72)


def test_first_booking_racing_an_attribution_wins_by_the_users_lock(ref, bookings) -> None:  # noqa: ANN001
    """Lock contract: accept and attribute both lock ``users`` first; whoever commits second sees the other.

    The booking side is a stand-in for ``accept_proposal`` (same first lock); the full accept path is stage 4.
    """
    referee = ref.client()
    code = ref.code(ref.client())
    with ref.pg_db.session() as accept:
        open_booking_for(bookings, accept, referee)  # holds the referee's users row, booking not committed yet
        thread, outcome = run_in_thread(lambda: ref.attribute(referee, code))
        wait_for_lock_waiters(bookings.world, 1)
        accept.commit()
    thread.join(30)
    assert isinstance(outcome.get("error"), DomainError)
    assert outcome["error"].code is ErrorCode.REFERRAL_WINDOW_CLOSED
    assert ref.count("referral_attributions", "referee_user_id = :u", u=referee) == 0


def test_self_referral_through_another_role_is_refused(ref) -> None:  # noqa: ANN001
    """One person with client and driver roles cannot invite themselves through either role."""
    person = ref.driver()
    with ref.pg_db.engine.begin() as conn:
        conn.execute(text("INSERT INTO user_roles (user_id, role, status) VALUES (:u, 'client', 'active')"), {"u": person})
    code = ref.code(person)
    for audience in ("client", "driver"):
        with pytest.raises(DomainError) as exc:
            ref.attribute(person, code, audience=audience)
        assert _code(exc) is ErrorCode.REFERRAL_SELF_REFERRAL
    assert ref.count("referral_attributions", "referee_user_id = :u", u=person) == 0
    with pytest.raises(DBAPIError):  # the DB refuses it as well
        with ref.pg_db.engine.begin() as conn:
            code_id = conn.execute(text("SELECT id FROM referral_codes WHERE owner_user_id = :u"), {"u": person}).scalar_one()
            conn.execute(text(
                "INSERT INTO referral_attributions (public_id, referee_user_id, family, referrer_user_id, referral_code_id, "
                "attributed_at, window_started_at, window_ends_at, idempotency_key, request_hash) VALUES "
                "(gen_random_uuid(), :u, 'client_acquisition', :u, :c, now(), now(), now() + interval '72 hours', 'k', :h)"),
                {"u": person, "c": code_id, "h": "0" * 64})


def test_same_idempotency_key_with_another_body_is_a_conflict(ref) -> None:  # noqa: ANN001
    referee = ref.client()
    code, other = ref.code(ref.client()), ref.code(ref.client())
    first = ref.attribute(referee, code, key="same-key")
    assert ref.attribute(referee, code, key="same-key") == first
    with pytest.raises(DomainError) as exc:
        ref.attribute(referee, other, key="same-key")
    assert _code(exc) is ErrorCode.IDEMPOTENCY_KEY_REUSED


def test_referral_refusals_never_break_registration(ref) -> None:  # noqa: ANN001
    """Sign-up and the referral attempt in one transaction: a refused code leaves the new account intact."""
    own_code_owner = ref.client()
    own_code = ref.code(own_code_owner)
    with ref.pg_db.session() as s:
        user_id = add_user(s, new_phone(), "client")
        for raw in ("not a code", "22222222", "ZZZZZZZZ"):
            with pytest.raises(DomainError) as exc:
                referral.attribute(s, referee_user_id=user_id, raw_code=raw, audience_role="client",
                                   idempotency_key=uuid.uuid4().hex)
            assert _code(exc) is ErrorCode.REFERRAL_CODE_INVALID
        with pytest.raises(DomainError):
            referral.attribute(s, referee_user_id=own_code_owner, raw_code=own_code, audience_role="client",
                               idempotency_key=uuid.uuid4().hex)
        s.commit()
    assert ref.count("users", "id = :u AND status = 'active'", u=user_id) == 1
    assert ref.count("referral_attributions", "referee_user_id IN (:a, :b)", a=user_id, b=own_code_owner) == 0


# --- enrollment (Q117, Q118) ------------------------------------------------------------------------------------


def test_attribution_alone_promises_nothing(ref) -> None:  # noqa: ANN001
    campaign = ref.campaign()
    referee = ref.client()
    ref.attribute(referee, ref.code(ref.client()))
    assert ref.promo.budget(campaign).committed_minor == 0
    assert ref.count("promo_obligations", "beneficiary_user_id = :u", u=referee) == 0


def test_enrollment_pins_terms_and_reserves_both_sides_once(ref) -> None:  # noqa: ANN001
    campaign = ref.campaign()
    referrer, referee = ref.client(), ref.client()
    attribution = ref.attribute(referee, ref.code(referrer))
    offer = ref.offer(campaign)
    enrollment = ref.enroll(referee, attribution, campaign, offer=offer)
    with ref.pg_db.engine.connect() as conn:
        row = conn.execute(text(
            "SELECT e.campaign_version_id, e.terms_fingerprint, e.service_type, e.family, e.enrolled_at, "
            "e.qualification_deadline, a.window_ends_at FROM promo_enrollments e "
            "JOIN referral_attributions a ON a.id = e.attribution_id WHERE e.id = :e"), {"e": enrollment}).mappings().one()
    assert (row["campaign_version_id"], row["terms_fingerprint"]) == (offer.campaign_version_id, offer.terms_fingerprint)
    assert (row["service_type"], row["family"]) == ("passenger", "client_acquisition")
    assert row["qualification_deadline"] - row["enrolled_at"] == timedelta(days=30)
    assert row["qualification_deadline"] != row["window_ends_at"]  # separate periods
    assert ref.count("promo_obligations", "enrollment_id = :e", e=enrollment) == 2
    assert ref.promo.budget(campaign).promised_minor == COMMITMENT
    with pytest.raises(DBAPIError) as info:  # accepted terms are immutable
        with ref.pg_db.engine.begin() as conn:
            conn.execute(text("UPDATE promo_enrollments SET qualification_deadline = qualification_deadline + interval '1 day' "
                              "WHERE id = :e"), {"e": enrollment})
    assert info.value.orig.diag.constraint_name == "promo_invalid_transition"


def test_repeated_enrollment_makes_one_promise_and_one_reserve(ref) -> None:  # noqa: ANN001
    campaign = ref.campaign()
    referee = ref.client()
    attribution = ref.attribute(referee, ref.code(ref.client()))
    offer = ref.offer(campaign)

    def enroll(index: int, session) -> int:  # noqa: ANN001
        row = referral.enroll(session, referee_user_id=referee, attribution_id=attribution, campaign_id=campaign,
                              accepted_campaign_version_id=offer.campaign_version_id,
                              accepted_terms_fingerprint=offer.terms_fingerprint, idempotency_key="one-key", keys=KEYS)
        session.commit()
        return row.id

    report = run_concurrently(6, enroll, engine=ref.pg_db.engine)
    assert not report.failures, [r.error for r in report.failures]
    assert len(set(report.values())) == 1
    assert ref.count("promo_obligations", "campaign_id = :c", c=campaign) == 2
    assert ref.promo.ledger_count(campaign, "promise") == 2
    with pytest.raises(DomainError) as exc:  # same key, different body
        ref.enroll(referee, attribution, ref.campaign(), key="one-key")
    assert _code(exc) is ErrorCode.IDEMPOTENCY_KEY_REUSED


def test_both_sides_are_reserved_or_nothing_is(ref) -> None:  # noqa: ANN001
    campaign = ref.campaign(allocate_minor=COMMITMENT)
    first = ref.client()
    ref.enroll(first, ref.attribute(first, ref.code(ref.client())), campaign)
    second = ref.client()
    attribution = ref.attribute(second, ref.code(ref.client()))
    with pytest.raises(DomainError) as exc:  # budget is gone: no enrollment, no half promise, no orphan reserve
        ref.enroll(second, attribution, campaign)
    assert _code(exc) is ErrorCode.PROMO_BUDGET_EXHAUSTED
    assert ref.count("promo_enrollments", "referee_user_id = :u", u=second) == 0
    assert ref.count("promo_obligations", "beneficiary_user_id = :u", u=second) == 0
    assert ref.promo.budget(campaign).committed_minor == COMMITMENT
    assert ref.count("referral_attributions", "id = :a", a=attribution) == 1  # who invited whom is still true
    assert ref.promo.issues(campaign) == []


def test_enrollments_racing_a_pause_are_consistent(ref) -> None:  # noqa: ANN001
    campaign = ref.campaign(allocate_minor=COMMITMENT * 20)
    offer = ref.offer(campaign)
    referees = [ref.client() for _ in range(8)]
    attributions = [ref.attribute(r, ref.code(ref.client())) for r in referees]

    def work(index: int, session) -> str:  # noqa: ANN001
        if index == 8:
            version = session.execute(text("SELECT version FROM promo_campaigns WHERE id = :c"), {"c": campaign}).scalar_one()
            service.pause_campaign(session, actor_user_id=ref.promo.super_id, actor_capabilities=SUPER_CAPS,
                                   campaign_id=campaign, expected_version=version, reason="synthetic pause")
        else:
            referral.enroll(session, referee_user_id=referees[index], attribution_id=attributions[index],
                            campaign_id=campaign, accepted_campaign_version_id=offer.campaign_version_id,
                            accepted_terms_fingerprint=offer.terms_fingerprint, idempotency_key="k", keys=KEYS)
        session.commit()
        return "ok"

    report = run_concurrently(9, work, engine=ref.pg_db.engine)
    enrolled = [r for r in report.successes if r.index < 8]
    assert {_err(r) for r in report.failures} <= {ErrorCode.FEATURE_DISABLED}
    assert 8 not in {r.index for r in report.failures}  # the pause itself always succeeds
    assert ref.count("promo_enrollments", "campaign_id = :c", c=campaign) == len(enrolled)
    assert ref.promo.budget(campaign).promised_minor == COMMITMENT * len(enrolled)
    assert ref.promo.issues(campaign) == []


def test_enrollment_racing_a_version_switch_never_mixes_terms(ref) -> None:  # noqa: ANN001
    campaign = ref.campaign(allocate_minor=COMMITMENT * 20)
    old_offer = ref.offer(campaign)
    referees = [ref.client() for _ in range(6)]
    attributions = [ref.attribute(r, ref.code(ref.client())) for r in referees]

    def work(index: int, session) -> str:  # noqa: ANN001
        if index == 6:
            version = service.add_campaign_version(session, actor_user_id=ref.promo.super_id, actor_capabilities=SUPER_CAPS,
                                                   campaign_id=campaign,
                                                   terms=synthetic_terms(referee_reward_minor=150_000))
            current = session.execute(text("SELECT version FROM promo_campaigns WHERE id = :c"), {"c": campaign}).scalar_one()
            service.activate_campaign(session, actor_user_id=ref.promo.super_id, actor_capabilities=SUPER_CAPS,
                                      campaign_id=campaign, version_id=version.id, expected_version=current, reason="v2")
        else:
            referral.enroll(session, referee_user_id=referees[index], attribution_id=attributions[index],
                            campaign_id=campaign, accepted_campaign_version_id=old_offer.campaign_version_id,
                            accepted_terms_fingerprint=old_offer.terms_fingerprint, idempotency_key="k", keys=KEYS)
        session.commit()
        return "ok"

    report = run_concurrently(7, work, engine=ref.pg_db.engine)
    assert {_err(r) for r in report.failures} <= {ErrorCode.VERSION_CONFLICT}
    with ref.pg_db.engine.connect() as conn:
        pinned = set(conn.execute(text("SELECT campaign_version_id FROM promo_enrollments WHERE campaign_id = :c"),
                                  {"c": campaign}).scalars())
        amounts = set(conn.execute(text("SELECT o.amount_minor FROM promo_obligations o WHERE o.campaign_id = :c "
                                        "AND o.side = 'referee'"), {"c": campaign}).scalars())
    assert pinned <= {old_offer.campaign_version_id}  # nobody was enrolled into v2 on v1's fingerprint
    assert amounts <= {200_000}


def test_a_new_client_is_new_once_across_services(ref) -> None:  # noqa: ANN001
    """Passenger and parcel share one "new client" reward; becoming a driver is a separate, allowed family."""
    passenger = ref.campaign()
    parcel = ref.parcel_campaign()
    person = ref.client()
    attribution = ref.attribute(person, ref.code(ref.client()))
    ref.enroll(person, attribution, passenger)
    with pytest.raises(DomainError) as exc:
        ref.enroll(person, attribution, parcel)
    assert _code(exc) is ErrorCode.REFERRAL_NOT_ELIGIBLE
    assert exc.value.details["reason"] == "already_enrolled_in_family"
    # the same person legitimately starts driving: driver acquisition is a different family
    from app.models import DriverProfile

    with ref.pg_db.session() as s:
        s.execute(text("INSERT INTO user_roles (user_id, role, status) VALUES (:u, 'driver', 'active')"), {"u": person})
        s.add(DriverProfile(user_id=person, verification_status="approved"))
        s.commit()
    driver_campaign = ref.campaign(kind=PromoCampaignKind.REFERRAL_DRIVER_DRIVER)
    driver_attribution = ref.attribute(person, ref.code(ref.driver()), audience="driver")
    ref.enroll(person, driver_attribution, driver_campaign)
    assert ref.count("promo_enrollments", "referee_user_id = :u", u=person) == 2


def test_inactive_referrer_opens_no_new_enrollment_and_keeps_old_ones(ref) -> None:  # noqa: ANN001
    campaign = ref.campaign()
    referrer = ref.client()
    code = ref.code(referrer)
    early, late = ref.client(), ref.client()
    early_enrollment = ref.enroll(early, ref.attribute(early, code), campaign)
    late_attribution = ref.attribute(late, code)
    with ref.pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE users SET status = 'blocked' WHERE id = :u"), {"u": referrer})
    with pytest.raises(DomainError) as exc:
        ref.enroll(late, late_attribution, campaign)
    assert exc.value.details["reason"] == "referrer_not_active"
    assert ref.count("promo_obligations", "enrollment_id = :e AND status = 'promised'", e=early_enrollment) == 2


def test_enrollment_after_the_first_service_is_refused(ref, bookings) -> None:  # noqa: ANN001
    campaign = ref.campaign()
    referee = ref.client()
    attribution = ref.attribute(referee, ref.code(ref.client()))
    with ref.pg_db.session() as s:
        open_booking_for(bookings, s, referee)
        s.commit()
    with pytest.raises(DomainError) as exc:
        ref.enroll(referee, attribution, campaign)
    assert exc.value.details["reason"] == "referee_not_new"


# --- protected identity (Q108) -------------------------------------------------------------------------------------


def test_no_identity_key_means_no_enrollment(ref) -> None:  # noqa: ANN001
    campaign = ref.campaign()
    referee = ref.client()
    attribution = ref.attribute(referee, ref.code(ref.client()))
    with pytest.raises(DomainError) as exc:
        ref.enroll(referee, attribution, campaign, keys=None)
    assert exc.value.details["reason"] == "identity_protection_not_ready"
    assert ref.count("promo_enrollments", "referee_user_id = :u", u=referee) == 0


def test_production_enrollment_needs_an_approved_retention(ref) -> None:  # noqa: ANN001
    campaign = ref.campaign()
    referee = ref.client()
    attribution = ref.attribute(referee, ref.code(ref.client()))
    with ref.pg_db.engine.begin() as conn:
        conn.execute(text("UPDATE platform_environment SET environment = 'production', set_by = 'test' WHERE id = 1"))
    with pytest.raises(DomainError) as exc:
        ref.enroll(referee, attribution, campaign)
    assert _code(exc) is ErrorCode.FEATURE_DISABLED
    assert exc.value.details["reason"] == "identity_protection_not_ready"


def test_key_rotation_keeps_history_and_the_key_is_never_stored(ref) -> None:  # noqa: ANN001
    user = ref.client()
    v1 = identity_service.keys_from_secret("rotation-secret-" + "y" * 40)
    v2 = identity_service.keys_from_secret("rotation-secret-" + "y" * 40, current_version=2, retained_versions=(1,))
    with ref.pg_db.session() as s:
        phone = s.execute(text("SELECT phone FROM users WHERE id = :u"), {"u": user}).scalar_one()
        first = identity_service.resolve_identity(s, user_id=user, phone=phone, window_started_at=utc_now(), keys=v1)
        again = identity_service.resolve_identity(s, user_id=user, phone=phone,
                                                  window_started_at=first.identity.first_window_started_at, keys=v2)
        s.commit()
        assert again.identity.id == first.identity.id and not again.matched_previous_account
    with ref.pg_db.engine.connect() as conn:
        rows = conn.execute(text("SELECT key_version, digest FROM promo_identity_digests WHERE identity_id = :i ORDER BY 1"),
                            {"i": first.identity.id}).all()
    assert [r.key_version for r in rows] == [1, 2]
    for _, digest in rows:
        assert all(ch in "0123456789abcdef" for ch in digest) and phone not in digest
    assert "rotation-secret" not in repr(v2)


def test_deleting_an_account_purges_its_digests_until_retention_is_approved(ref) -> None:  # noqa: ANN001
    user = ref.client()
    campaign = ref.campaign()
    ref.enroll(user, ref.attribute(user, ref.code(ref.client())), campaign)
    with ref.pg_db.session() as s:
        identity_service.on_account_deleted(s, user_id=user)  # Q108: nothing approved -> purge
        s.commit()
    with ref.pg_db.engine.connect() as conn:
        identity = conn.execute(text("SELECT id, current_user_id FROM promo_identities i WHERE EXISTS "
                                     "(SELECT 1 FROM promo_enrollments e WHERE e.referee_identity_id = i.id AND e.referee_user_id = :u)"),
                                {"u": user}).one()
        assert identity.current_user_id is None
        assert conn.execute(text("SELECT count(*) FROM promo_identity_digests WHERE identity_id = :i"),
                            {"i": identity.id}).scalar_one() == 0


def test_recycled_number_goes_to_review_and_never_blocks_service(ref) -> None:  # noqa: ANN001
    """With a (synthetic) approved retention the old digest is kept; a new account with that number is not
    auto-enrolled but can still sign up, attribute and use the service."""
    campaign = ref.campaign()
    old = ref.client()
    ref.enroll(old, ref.attribute(old, ref.code(ref.client())), campaign)
    with ref.pg_db.session() as s:
        phone = s.execute(text("SELECT phone FROM users WHERE id = :u"), {"u": old}).scalar_one()
        identity_service.on_account_deleted(s, user_id=old, policy=IdentityRetentionPolicy(timedelta(days=30)))
        s.execute(text("UPDATE users SET phone = :p, status = 'deleted' WHERE id = :u"), {"p": f"deleted:{old}", "u": old})
        s.commit()
    with ref.pg_db.session() as s:
        newcomer = add_user(s, phone, "client")
        s.commit()
    attribution = ref.attribute(newcomer, ref.code(ref.client()))  # attribution works
    with pytest.raises(DomainError) as exc:
        ref.enroll(newcomer, attribution, campaign)
    assert exc.value.details["reason"] == "identity_needs_review"
    assert ref.count("users", "id = :u AND status = 'active'", u=newcomer) == 1


def test_a_failed_transaction_leaves_no_orphan_attribution_or_enrollment(ref) -> None:  # noqa: ANN001
    """The caller's transaction fails after a successful attribute + enroll: nothing of either survives."""
    campaign = ref.campaign()
    referee = ref.client()
    code = ref.code(ref.client())
    offer = ref.offer(campaign)
    with ref.pg_db.session() as s:
        attribution = referral.attribute(s, referee_user_id=referee, raw_code=code, audience_role="client",
                                         idempotency_key="k")
        referral.enroll(s, referee_user_id=referee, attribution_id=attribution.id, campaign_id=campaign,
                        accepted_campaign_version_id=offer.campaign_version_id,
                        accepted_terms_fingerprint=offer.terms_fingerprint, idempotency_key="k", keys=KEYS)
        s.rollback()  # e.g. the surrounding sign-up step failed
    assert ref.count("referral_attributions", "referee_user_id = :u", u=referee) == 0
    assert ref.count("promo_enrollments", "referee_user_id = :u", u=referee) == 0
    assert ref.promo.budget(campaign).committed_minor == 0

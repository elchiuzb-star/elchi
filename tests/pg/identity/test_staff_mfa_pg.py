"""Staff MFA (ADR-0021, accepted 17.09.2026) - spec §17.5, §17.6.

These tests are aimed at the ways an MFA implementation usually fails to be MFA at all:

* somebody approves their own second factor;
* a recovery code quietly becomes a way to approve money;
* the same six digits work twice;
* the audit trail can be edited by whoever compromised the account;
* enforcement locks the only super_admin out of the platform.
"""

from __future__ import annotations

import time

import pyotp
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.contracts.enums import Capability
from app.contracts.errors import DomainError, ErrorCode
from app.core.config import settings
from app.modules.identity import mfa
from tests.pg.bookings.conftest import BW, bw  # noqa: F401  (shared staff/world fixtures)


def _staff(session, role: str = "super_admin", phone_suffix: str = "0001") -> int:
    return session.scalar(
        text(
            "INSERT INTO users (phone, role, status, is_phone_verified) "
            "VALUES (:phone, :role, 'active', true) RETURNING id"
        ),
        {"phone": f"+99893100{phone_suffix}", "role": role},
    )


def _code(session, user_id: int, *, step: int = 0) -> str:
    """Generate a live code the way the staff member's phone would."""
    factor = session.scalar(
        text("SELECT id FROM staff_mfa_factors WHERE user_id = :u ORDER BY id DESC LIMIT 1"), {"u": user_id}
    )
    assert factor is not None
    row = session.execute(
        text("SELECT secret_cipher, public_id, secret_key_version FROM staff_mfa_factors WHERE id = :i"),
        {"i": factor},
    ).one()
    from app.core.config import settings
    from app.core.secret_box import open_sealed

    secret = open_sealed(
        settings.secret_key, mfa.SECRET_PURPOSE, row[0], aad=str(row[1]), key_version=row[2]
    )
    totp = pyotp.TOTP(secret, interval=mfa.TOTP_INTERVAL_SECONDS)
    return totp.at(int(time.time()) + step * mfa.TOTP_INTERVAL_SECONDS)


def test_the_enroller_cannot_activate_their_own_factor(bw: BW) -> None:  # noqa: F811
    with bw.db.session() as session:
        subject = _staff(session, phone_suffix="0101")
        session.commit()

    with bw.db.session() as session:
        mfa.enroll(session, user_id=subject, account_name="finance@elchi")
        session.commit()

    with bw.db.session() as session:
        with pytest.raises(DomainError) as refused:
            mfa.activate(session, actor_user_id=subject, subject_user_id=subject, code=_code(session, subject))
        assert refused.value.code is ErrorCode.FORBIDDEN
        assert refused.value.details["reason"] == "self_activation"


def test_the_database_refuses_a_self_activated_factor_even_by_raw_sql(bw: BW) -> None:  # noqa: F811
    """The Python check is a message; this is the rule. An attacker with app-role SQL cannot get around it."""
    with bw.db.session() as session:
        subject = _staff(session, phone_suffix="0102")
        session.commit()
    with bw.db.session() as session:
        mfa.enroll(session, user_id=subject, account_name="finance@elchi")
        session.commit()

    with bw.db.session() as session, pytest.raises((IntegrityError, DBAPIError)) as refused:
        session.execute(
            text(
                "UPDATE staff_mfa_factors SET status = 'active', activated_at = now(), activated_by = :u "
                "WHERE user_id = :u"
            ),
            {"u": subject},
        )
        session.commit()
    assert "two_person" in str(refused.value)


def test_another_super_admin_activates_and_a_used_code_cannot_be_replayed(bw: BW) -> None:  # noqa: F811
    with bw.db.session() as session:
        subject = _staff(session, phone_suffix="0103")
        session.commit()
    with bw.db.session() as session:
        mfa.enroll(session, user_id=subject, account_name="ops@elchi")
        session.commit()

    with bw.db.session() as session:
        factor = mfa.activate(
            session, actor_user_id=bw.super_id, subject_user_id=subject, code=_code(session, subject)
        )
        assert factor.status == "active" and factor.activated_by == bw.super_id
        session.commit()

    with bw.db.session() as session:
        code = _code(session, subject)
        assert mfa.verify(session, user_id=subject, code=code) is True
        session.commit()
    with bw.db.session() as session:
        # The same six digits are still "valid" as far as the clock goes - and are refused anyway.
        assert mfa.verify(session, user_id=subject, code=code) is False
        session.commit()
    with bw.db.session() as session:
        replayed = session.scalar(
            text(
                "SELECT count(*) FROM staff_mfa_events WHERE user_id = :u AND event_type = 'verify_failed' "
                "AND detail->>'reason' = 'replayed'"
            ),
            {"u": subject},
        )
        assert replayed == 1


def test_a_recovery_code_restores_enrollment_and_nothing_else(bw: BW) -> None:  # noqa: F811
    """Q17/Q49: recovery must never become a second approver or a step-up."""
    with bw.db.session() as session:
        subject = _staff(session, phone_suffix="0104")
        session.commit()
    with bw.db.session() as session:
        enrollment = mfa.enroll(session, user_id=subject, account_name="finance@elchi")
        session.commit()
        codes = enrollment.recovery_codes
    with bw.db.session() as session:
        mfa.activate(session, actor_user_id=bw.super_id, subject_user_id=subject, code=_code(session, subject))
        session.commit()

    with bw.db.session() as session:
        assert mfa.consume_recovery_code(session, user_id=subject, code=codes[0]) is True
        session.commit()

    with bw.db.session() as session:
        state = mfa.state(session, subject)
        assert state.active is False, "the factor is revoked, not left half-trusted"
        assert state.step_up_fresh() is False, "recovery is not a step-up"
        assert mfa.unused_recovery_code_count(session, subject) == mfa.RECOVERY_CODE_COUNT - 1
        # the same code cannot be spent twice
        assert mfa.consume_recovery_code(session, user_id=subject, code=codes[0]) is False
        session.commit()


def test_re_enrolling_invalidates_the_previous_paper_codes(bw: BW) -> None:  # noqa: F811
    with bw.db.session() as session:
        subject = _staff(session, phone_suffix="0105")
        session.commit()
    with bw.db.session() as session:
        first = mfa.enroll(session, user_id=subject, account_name="ops@elchi")
        session.commit()
    with bw.db.session() as session:
        mfa.enroll(session, user_id=subject, account_name="ops@elchi")
        session.commit()
    with bw.db.session() as session:
        assert mfa.consume_recovery_code(session, user_id=subject, code=first.recovery_codes[0]) is False
        assert mfa.unused_recovery_code_count(session, subject) == mfa.RECOVERY_CODE_COUNT


def test_the_audit_trail_cannot_be_rewritten(bw: BW) -> None:  # noqa: F811
    with bw.db.session() as session:
        subject = _staff(session, phone_suffix="0106")
        session.commit()
    with bw.db.session() as session:
        mfa.enroll(session, user_id=subject, account_name="ops@elchi")
        session.commit()

    for statement in (
        "UPDATE staff_mfa_events SET event_type = 'step_up' WHERE user_id = :u",
        "DELETE FROM staff_mfa_events WHERE user_id = :u",
    ):
        with bw.db.session() as session, pytest.raises((IntegrityError, DBAPIError)) as refused:
            session.execute(text(statement), {"u": subject})
            session.commit()
        assert "append-only" in str(refused.value)


def test_a_secret_moved_onto_another_factor_row_does_not_decrypt(bw: BW) -> None:  # noqa: F811
    """AES-GCM binds the secret to its row, so copying ciphertext between staff accounts fails closed."""
    with bw.db.session() as session:
        first = _staff(session, phone_suffix="0107")
        second = _staff(session, phone_suffix="0108")
        session.commit()
    with bw.db.session() as session:
        mfa.enroll(session, user_id=first, account_name="a@elchi")
        mfa.enroll(session, user_id=second, account_name="b@elchi")
        session.commit()

    with bw.db.session() as session:
        session.execute(
            text(
                "UPDATE staff_mfa_factors SET secret_cipher = "
                "(SELECT secret_cipher FROM staff_mfa_factors WHERE user_id = :a) WHERE user_id = :b"
            ),
            {"a": first, "b": second},
        )
        session.commit()
    with bw.db.session() as session:
        with pytest.raises(DomainError) as refused:
            mfa.activate(session, actor_user_id=bw.super_id, subject_user_id=second, code="000000")
        assert refused.value.details["reason"] == "factor_unreadable"


def test_step_up_is_audit_only_while_there_is_one_super_admin(bw: BW) -> None:  # noqa: F811
    """The pilot may run with a single super_admin; enforcing MFA there would lock the platform, not secure it."""
    with bw.db.session() as session:
        assert mfa.active_super_admin_count(session) >= 1
        if mfa.audit_only(session):  # true by default: settings.staff_mfa_mode is audit_only
            # allowed, and recorded so the gap is visible in the trail
            mfa.require_step_up(session, user_id=bw.super_id, capability=Capability.FINANCE_TOPUP_APPROVE)
            session.commit()
            recorded = session.scalar(
                text(
                    "SELECT count(*) FROM staff_mfa_events WHERE user_id = :u "
                    "AND detail->>'mode' = 'audit_only'"
                ),
                {"u": bw.super_id},
            )
            assert recorded >= 1


def test_a_second_super_admin_alone_does_not_switch_enforcement_on(bw: BW) -> None:  # noqa: F811
    """Hiring a second admin must not be the thing that starts refusing money commands.

    Enforcement is an operational step somebody takes (``staff_mfa_mode``), announced and prepared. If it
    switched itself on the day a second super_admin was created, finance would find top-ups failing with no
    warning and no enrolled factor.
    """
    with bw.db.session() as session:
        _staff(session, phone_suffix="0112")
        session.commit()
    with bw.db.session() as session:
        assert settings.staff_mfa_mode == mfa.AUDIT_ONLY, "the shipped default is audit-only"
        assert mfa.audit_only(session) is True
        mfa.require_step_up(session, user_id=bw.super_id, capability=Capability.FINANCE_TOPUP_APPROVE)
        session.commit()


def test_enforcement_still_refuses_to_apply_to_a_lone_super_admin(
    bw: BW, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """Even with the stage turned up, one super_admin means audit-only - nobody gets locked out of the pilot."""
    monkeypatch.setattr(settings, "staff_mfa_mode", mfa.ENFORCE_PRIVILEGED)
    with bw.db.session() as session:
        if mfa.active_super_admin_count(session) == 1:
            assert mfa.audit_only(session) is True
            mfa.require_step_up(session, user_id=bw.super_id, capability=Capability.FINANCE_TOPUP_APPROVE)
            session.commit()


def test_step_up_blocks_a_money_command_when_enforcement_is_on(
    bw: BW, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with bw.db.session() as session:
        _staff(session, phone_suffix="0109")  # two super_admins: enforcement is now safe to apply
        session.commit()
    monkeypatch.setattr(settings, "staff_mfa_mode", mfa.ENFORCE_PRIVILEGED)

    with bw.db.session() as session:
        assert mfa.audit_only(session) is False
        with pytest.raises(DomainError) as refused:
            mfa.require_step_up(session, user_id=bw.super_id, capability=Capability.FINANCE_TOPUP_APPROVE)
        assert refused.value.code is ErrorCode.FORBIDDEN
        assert refused.value.details["reason"] == "step_up_required"
        # a capability outside the list is untouched: MFA does not creep into ordinary reads
        mfa.require_step_up(session, user_id=bw.super_id, capability=Capability.OPS_VIEW)


def test_a_fresh_step_up_lets_the_money_command_through(
    bw: BW, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    with bw.db.session() as session:
        second = _staff(session, phone_suffix="0110")
        session.commit()
    monkeypatch.setattr(settings, "staff_mfa_mode", mfa.ENFORCE_PRIVILEGED)
    with bw.db.session() as session:
        mfa.enroll(session, user_id=bw.super_id, account_name="super@elchi")
        session.commit()
    with bw.db.session() as session:
        mfa.activate(
            session, actor_user_id=second, subject_user_id=bw.super_id, code=_code(session, bw.super_id)
        )
        session.commit()

    with bw.db.session() as session:
        assert mfa.step_up(session, user_id=bw.super_id, code=_code(session, bw.super_id)) is True
        session.commit()
    with bw.db.session() as session:
        mfa.require_step_up(session, user_id=bw.super_id, capability=Capability.FINANCE_TOPUP_APPROVE)
        assert mfa.state(session, bw.super_id).step_up_fresh() is True


def test_no_secret_or_code_is_ever_stored_in_the_event_trail(bw: BW) -> None:  # noqa: F811
    with bw.db.session() as session:
        subject = _staff(session, phone_suffix="0111")
        session.commit()
    with bw.db.session() as session:
        enrollment = mfa.enroll(session, user_id=subject, account_name="ops@elchi")
        session.commit()
    with bw.db.session() as session:
        details = session.execute(
            text("SELECT detail::text FROM staff_mfa_events WHERE user_id = :u"), {"u": subject}
        ).scalars().all()
    blob = " ".join(details)
    assert enrollment.secret not in blob
    for code in enrollment.recovery_codes:
        assert code not in blob

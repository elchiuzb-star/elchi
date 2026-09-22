"""Wave 7 / U3 + U7 + Q87: what the platform does while the two decisions are still open.

U3 (push provider): in-app notifications are the only channel. This pins that a disabled provider makes **no
external call and writes no push delivery row** - the dispatcher does not "prepare" a push that nobody will send,
and a booking never depends on one (AC34).

U7 / Q87 (support phone): with ``ELCHI_SUPPORT_PHONE`` unset, S13 answers ``available=false`` with no invented
number and no invented hours - and the passenger service **cannot be switched on in production**, because §16
forbids promising help that does not exist.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.contracts.enums import Capability, FeatureFlagKey, FlagScopeType
from app.contracts.errors import DomainError, ErrorCode
from app.modules.communications import providers as push_providers
from app.modules.geo import service as geo_service
from app.modules.geo.flags import COUNTRY_SCOPE_REF
from app.modules.trust_support import config as support_config
from tests.pg.bookings.conftest import (  # noqa: F401  (shared A4 fixtures)
    BW,
    auth,
    bw,
    rows,
    scalar,
)
from tests.pg.identity.a1_world import world  # noqa: F401  (shared A1 fixture)

pytestmark = pytest.mark.pg


def test_support_contacts_without_a_phone_are_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = support_config.SupportSettings(phone=None, hours_text=None)
    assert support_config.support_contacts(settings) == (False, None, None)

    # a configured phone is shown as configured - nothing is invented on either side
    configured = support_config.SupportSettings(phone="+998711234567", hours_text="Du-Ju 09:00-18:00")
    available, phone, hours = support_config.support_contacts(configured)
    assert (available, phone, hours) == (True, "+998711234567", "Du-Ju 09:00-18:00")

    # §16: an hours text that promises 24/7 or a response time is dropped, not displayed
    promising = support_config.SupportSettings(phone="+998711234567", hours_text="24/7 xizmat, 5 daqiqada javob")
    available, phone, hours = support_config.support_contacts(promising)
    assert available is True and phone == "+998711234567" and hours is None


def test_passenger_flag_cannot_be_enabled_in_production_without_support(
    bw: BW, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """Q87: the passenger service waits for a reachable support phone, not the other way round."""
    # the fixture leaves the flag on; switch it off first so the next call is a real "enable"
    with bw.db.session() as session:
        current = scalar(
            bw.db,
            "SELECT version FROM feature_flag_values WHERE flag_key = 'passenger_enabled' AND scope_type = 'country'",
        )
        geo_service.set_flag_value(
            session, actor_user_id=bw.super_id, actor_capabilities=[Capability.OPS_FEATURE_FLAG_MANAGE],
            actor_is_super_admin=True, flag_key=FeatureFlagKey.PASSENGER_ENABLED,
            scope_type=FlagScopeType.COUNTRY, scope_ref=COUNTRY_SCOPE_REF, enabled=False,
            reason="wave 7 test", expected_version=int(current),
        )
        session.commit()
        disabled_version = scalar(
            bw.db,
            "SELECT version FROM feature_flag_values WHERE flag_key = 'passenger_enabled' AND scope_type = 'country'",
        )

    monkeypatch.setattr(geo_service, "is_production", lambda db: True)
    monkeypatch.setattr(support_config, "support_contacts", lambda settings=None: (False, None, None))

    with bw.db.session() as session, pytest.raises(DomainError) as refused:
        geo_service.set_flag_value(
            session, actor_user_id=bw.super_id, actor_capabilities=[Capability.OPS_FEATURE_FLAG_MANAGE],
            actor_is_super_admin=True, flag_key=FeatureFlagKey.PASSENGER_ENABLED,
            scope_type=FlagScopeType.COUNTRY, scope_ref=COUNTRY_SCOPE_REF, enabled=True,
            reason="pilot start", approval_reference="legal/2026-09-17", expected_version=int(disabled_version),
        )
    assert refused.value.code is ErrorCode.VALIDATION_ERROR
    assert refused.value.details["reason"] == "support_contact_not_configured"


def test_disabled_push_provider_sends_nothing_and_writes_nothing(bw: BW) -> None:  # noqa: F811
    """U3: until a provider is decided, the in-app inbox is the only channel."""
    push_providers.set_push_provider(None)
    provider = push_providers.get_push_provider()
    assert isinstance(provider, push_providers.DisabledPushProvider)

    from app.modules.communications import jobs as comms_jobs

    before = scalar(bw.db, "SELECT count(*) FROM notification_deliveries WHERE channel <> 'in_app'")
    # The worker task short-circuits on a disabled provider: no DB work, no network, no lock taken.
    assert comms_jobs.push_delivery_task(engine=bw.db.engine) == 0
    after = scalar(bw.db, "SELECT count(*) FROM notification_deliveries WHERE channel <> 'in_app'")
    assert after == before, "a disabled provider must not create push rows"


def test_disabled_provider_refuses_to_send_a_message() -> None:
    """The port itself is safe: calling it with a provider that is off never reaches the network."""
    push_providers.set_push_provider(None)
    provider = push_providers.get_push_provider()
    message = push_providers.PushMessage(
        delivery_id="ntf_test", user_id=1, channel=provider.channel, device_ids=(), payload={}
    )
    result = provider.send(message)
    assert result.ok is False
    assert result.error

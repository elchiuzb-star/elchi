"""ADR-0022 FCM adapter - the rules that must hold before anyone turns push on.

No test here touches the network: the transport is a fake, which is the point of the seam in
``communications.fcm``. What is checked is what a provider integration usually gets wrong - leaking user data
into a notification, retrying a dead device forever, and being "on" before it is configured.
"""

from __future__ import annotations

import pytest

from app.contracts.enums import NotificationChannel
from app.modules.communications import fcm
from app.modules.communications.providers import PushMessage


def message(payload: dict | None = None, devices: tuple[str, ...] = ("dev_1",)) -> PushMessage:
    return PushMessage(
        delivery_id="ntf_1",
        user_id=7,
        channel=NotificationChannel.WEB_PUSH,
        device_ids=devices,
        payload=payload or {"event_type": "booking.accepted", "aggregate_id": "bkg_1", "title_key": "booking_accepted"},
    )


class FakeTransport:
    def __init__(self, *responses: tuple[int, dict]) -> None:
        self.responses = list(responses) or [(200, {})]
        self.calls: list[dict] = []

    def post(self, url: str, *, headers: dict, json: dict) -> tuple[int, dict]:
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]


class FakeCredentials:
    project_id = "elchi-test"

    def __init__(self, token: str | None = "ya29.fake") -> None:
        self._token = token

    def access_token(self) -> str | None:
        return self._token


def provider(*responses: tuple[int, dict], token: str | None = "fcm-token") -> tuple[fcm.FcmPushProvider, FakeTransport]:
    transport = FakeTransport(*responses)
    return (
        fcm.FcmPushProvider(
            credentials=FakeCredentials(), transport=transport, token_lookup=lambda _device_id: token
        ),
        transport,
    )


def test_the_provider_is_inert_until_it_is_configured() -> None:
    """Importing the adapter must not switch push on - the decision to enable it is a separate, human one."""
    bare = fcm.FcmPushProvider()
    assert bare.enabled is False
    result = bare.send(message())
    assert result.ok is False and result.error == "fcm_not_configured"


def test_a_payload_key_outside_the_allowlist_is_refused_before_it_leaves() -> None:
    """§15: a phone number or a proof code must not be able to reach a push provider, even by mistake."""
    with pytest.raises(ValueError, match="allowlist"):
        fcm.build_request(message({"event_type": "x", "phone": "+998901234567"}), token="t")


def test_the_body_carries_a_key_not_a_sentence() -> None:
    body = fcm.build_request(message(), token="fcm-token")["message"]
    assert body["token"] == "fcm-token"
    assert "notification" not in body, "an OS-rendered title would have to contain real text"
    assert set(body["data"]) == {"event_type", "aggregate_id", "title_key"}
    assert body["data"]["title_key"] == "booking_accepted"


@pytest.mark.parametrize(
    ("status_code", "body", "retry", "gone"),
    [
        (200, {}, False, False),
        (503, {"error": {"status": "UNAVAILABLE"}}, True, False),
        (429, {}, True, False),
        (404, {"error": {"status": "UNREGISTERED"}}, False, True),
        (400, {"error": {"status": "INVALID_ARGUMENT"}}, False, True),
        (401, {"error": {"status": "UNAUTHENTICATED"}}, False, False),
    ],
)
def test_responses_are_classified_for_the_outbox(status_code: int, body: dict, retry: bool, gone: bool) -> None:
    verdict = fcm.classify(status_code, body)
    assert (verdict.retry, verdict.device_gone) == (retry, gone)


def test_an_uninstalled_app_is_not_retried_forever() -> None:
    sender, _transport = provider((404, {"error": {"status": "UNREGISTERED"}}))
    result = sender.send(message())
    assert result.ok is False
    assert sender.last_verdict.device_gone is True and sender.last_verdict.retry is False


def test_a_device_registered_before_0073_is_skipped_not_crashed() -> None:
    """Old rows hold only a hash, so there is nothing to send to - that is a skip, not an exception."""
    sender, transport = provider(token=None)
    result = sender.send(message())
    assert result.ok is False and result.error == "device_token_unavailable"
    assert transport.calls == [], "no request is made without a token"


def test_one_delivered_device_is_a_success_even_if_another_is_dead() -> None:
    sender, transport = provider((200, {}), (404, {"error": {"status": "UNREGISTERED"}}), token="fcm-token")
    assert sender.send(message(devices=("dev_1", "dev_2"))).ok is True
    assert len(transport.calls) == 2


def test_missing_access_token_fails_closed_without_calling_out() -> None:
    transport = FakeTransport()
    sender = fcm.FcmPushProvider(
        credentials=FakeCredentials(token=None), transport=transport, token_lookup=lambda _d: "fcm-token"
    )
    result = sender.send(message())
    assert result.ok is False and result.error == "fcm_no_access_token"
    assert transport.calls == []

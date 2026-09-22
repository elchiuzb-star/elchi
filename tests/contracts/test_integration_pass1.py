"""Contract additions from wave-1 integration pass 1 and their re-exports."""

import pytest

from app.contracts.enums import CorridorRolloutState, MatchReason
from app.contracts.ids import PublicIdPrefix, format_public_id, new_public_uuid, parse_public_id
from app.contracts.money import TWO_PERSON_APPROVAL_THRESHOLD_MINOR, major_to_minor
from app.contracts.state_machines import ALL_MACHINES, CORRIDOR_ROLLOUT


@pytest.mark.parametrize(
    ("prefix", "value"),
    [(PublicIdPrefix.LEDGER_ADJUSTMENT, "adj"), (PublicIdPrefix.REGION, "reg"), (PublicIdPrefix.DISTRICT, "dst")],
)
def test_new_public_id_prefixes_round_trip(prefix: PublicIdPrefix, value: str) -> None:
    assert prefix.value == value
    uid = new_public_uuid()
    assert parse_public_id(format_public_id(prefix, uid), prefix) == uid


def test_public_id_prefixes_are_unique() -> None:
    values = [p.value for p in PublicIdPrefix]
    assert len(values) == len(set(values))


def test_match_reason_values() -> None:
    assert {r.value for r in MatchReason} == {
        "full_route", "intermediate_segment", "pickup_at_stop", "dropoff_at_stop", "pickup_detour",
        "dropoff_detour", "nearby_stop", "time_differs", "same_stop", "pickup_not_on_route",
        "dropoff_not_on_route", "reverse_direction", "detour_order_unknown", "time_window_mismatch",
        "detour_limit_exceeded", "routing_unavailable",
    }


def test_geo_re_exports_are_the_contract_enums() -> None:
    from app.modules.geo.schemas import CorridorRolloutState as GeoRollout
    from app.modules.geo.types import MatchReason as GeoMatchReason

    assert GeoMatchReason is MatchReason
    assert GeoRollout is CorridorRolloutState


def test_corridor_rollout_machine() -> None:
    assert CORRIDOR_ROLLOUT in ALL_MACHINES
    assert CORRIDOR_ROLLOUT.initial == {"draft"}
    assert CORRIDOR_ROLLOUT.terminal == {"closed"}
    expected = {
        "draft": {"internal", "closed"},
        "internal": {"draft", "pilot", "closed"},
        "pilot": {"internal", "active", "closed"},
        "active": {"pilot", "closed"},
        "closed": set(),
    }
    actual = {s.value: {t.target for t in CORRIDOR_ROLLOUT.transitions if t.source == s.value} for s in CorridorRolloutState}
    assert actual == expected
    assert not CORRIDOR_ROLLOUT.is_allowed("draft", "active")
    assert not CORRIDOR_ROLLOUT.is_allowed("closed", "draft")


def test_geo_service_transitions_match_contract() -> None:
    from app.modules.geo.service import ROLLOUT_TRANSITIONS

    for source, targets in ROLLOUT_TRANSITIONS.items():
        assert {t.value for t in targets} == {
            t.target for t in CORRIDOR_ROLLOUT.transitions if t.source == source.value
        }, source


def test_proposal_rejected_event_is_catalogued() -> None:
    from app.contracts.enums import EventType
    from app.contracts.events import EVENT_AUDIENCES, EVENT_PAYLOAD_ALLOWLIST, EventAudience, payload_for_audience

    assert EventType.PROPOSAL_REJECTED.value == "proposal.rejected"
    assert EVENT_PAYLOAD_ALLOWLIST[EventType.PROPOSAL_REJECTED] == {"listing_id", "thread_id", "revision", "reason_code"}
    assert EventAudience.CLIENT in EVENT_AUDIENCES[EventType.PROPOSAL_REJECTED]
    payload = {"thread_id": "prp_x", "revision": 2, "reason_code": "price"}
    assert payload_for_audience(EventType.PROPOSAL_REJECTED, payload, EventAudience.CLIENT) == payload


def test_two_person_threshold_is_one_million_som_and_matches_wallet() -> None:
    assert TWO_PERSON_APPROVAL_THRESHOLD_MINOR == major_to_minor("1000000")
    from app.modules.wallet.service import LARGE_AMOUNT_THRESHOLD_MINOR

    assert LARGE_AMOUNT_THRESHOLD_MINOR == TWO_PERSON_APPROVAL_THRESHOLD_MINOR

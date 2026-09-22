"""Unit tests: totals, price basis, D9 quantity, proposal TTL, revision limit, DTO shape (AC01, AC04, AC43)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.contracts.enums import ActorSide, ListingKind, PriceBasis, ServiceType
from app.contracts.errors import DomainError, ErrorCode
from app.modules.marketplace.rules import (
    MAX_PRICE_REVISIONS_PER_SIDE,
    PROPOSAL_MAX_TTL,
    PROPOSAL_NEAR_DEPARTURE_TTL,
    check_proposal_quantity,
    compute_total_minor,
    counterparty,
    display_name,
    ensure_price_basis_allowed,
    listing_quantity,
    next_price_revision_count,
    parcel_volume_ml,
    proposal_expires_at,
    proposer_side,
)
from app.modules.marketplace.schemas import ListingCreate, PassengerDetails, ProposalCounter

NOW = datetime(2026, 9, 13, 8, 0, tzinfo=timezone.utc)


def test_ac01_two_seats_times_200000_som_is_400000_som() -> None:
    assert compute_total_minor(PriceBasis.PER_SEAT, 20_000_000, 2) == 40_000_000


def test_total_basis_ignores_quantity() -> None:
    assert compute_total_minor(PriceBasis.TOTAL, 7_000_000, 1) == 7_000_000
    assert compute_total_minor(PriceBasis.TOTAL, 30_000_000, 3) == 30_000_000


@pytest.mark.parametrize("bad", [0, -1, 1.5, True])
def test_total_rejects_non_positive_or_float(bad: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        compute_total_minor(PriceBasis.PER_SEAT, bad, 2)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kind", "service", "basis", "allowed"),
    [
        (ListingKind.REQUEST, ServiceType.PASSENGER, PriceBasis.PER_SEAT, True),
        (ListingKind.REQUEST, ServiceType.PASSENGER, PriceBasis.TOTAL, True),
        (ListingKind.REQUEST, ServiceType.PARCEL, PriceBasis.PER_SEAT, False),
        (ListingKind.TRIP_OFFER, ServiceType.PASSENGER, PriceBasis.TOTAL, False),
        (ListingKind.TRIP_OFFER, ServiceType.PARCEL, PriceBasis.TOTAL, True),
    ],
)
def test_price_basis_table(kind: ListingKind, service: ServiceType, basis: PriceBasis, allowed: bool) -> None:
    if allowed:
        ensure_price_basis_allowed(kind, service, basis)
    else:
        with pytest.raises(DomainError) as info:
            ensure_price_basis_allowed(kind, service, basis)
        assert info.value.code is ErrorCode.PRICE_BASIS_NOT_ALLOWED


def test_listing_quantity_by_kind() -> None:
    assert listing_quantity(ListingKind.REQUEST, ServiceType.PASSENGER, seat_count=3, trip_seat_capacity=None) == 3
    assert listing_quantity(ListingKind.TRIP_OFFER, ServiceType.PASSENGER, seat_count=None, trip_seat_capacity=4) == 4
    assert listing_quantity(ListingKind.REQUEST, ServiceType.PARCEL, seat_count=None, trip_seat_capacity=None) == 1
    with pytest.raises(DomainError):
        listing_quantity(ListingKind.TRIP_OFFER, ServiceType.PASSENGER, seat_count=None, trip_seat_capacity=0)


def test_d9_passenger_request_is_never_split() -> None:
    check_proposal_quantity(listing_kind=ListingKind.REQUEST, service_type=ServiceType.PASSENGER, listing_quantity=2, quantity=2)
    for quantity in (1, 3):
        with pytest.raises(DomainError) as info:
            check_proposal_quantity(
                listing_kind=ListingKind.REQUEST, service_type=ServiceType.PASSENGER, listing_quantity=2, quantity=quantity
            )
        assert info.value.code is ErrorCode.QUANTITY_MISMATCH
        assert info.value.details == {"required_quantity": 2, "quantity": quantity}


@pytest.mark.parametrize("kind", list(ListingKind))
def test_d9_parcel_quantity_is_one(kind: ListingKind) -> None:
    check_proposal_quantity(listing_kind=kind, service_type=ServiceType.PARCEL, listing_quantity=1, quantity=1)
    with pytest.raises(DomainError) as info:
        check_proposal_quantity(listing_kind=kind, service_type=ServiceType.PARCEL, listing_quantity=1, quantity=2)
    assert info.value.code is ErrorCode.QUANTITY_MISMATCH


def test_trip_offer_passenger_quantity_left_to_capacity_check() -> None:
    check_proposal_quantity(listing_kind=ListingKind.TRIP_OFFER, service_type=ServiceType.PASSENGER, listing_quantity=4, quantity=1)


def test_ttl_is_two_hours_when_departure_is_far() -> None:
    departure = NOW + timedelta(hours=10)
    assert proposal_expires_at(now=NOW, departure_at=departure, booking_cutoff_at=departure) == NOW + PROPOSAL_MAX_TTL


def test_ttl_is_ten_minutes_near_departure_including_the_boundary() -> None:
    for departure in (NOW + timedelta(hours=1), NOW + PROPOSAL_MAX_TTL):
        assert (
            proposal_expires_at(now=NOW, departure_at=departure, booking_cutoff_at=departure)
            == NOW + PROPOSAL_NEAR_DEPARTURE_TTL
        )


def test_ttl_never_after_cutoff_or_listing_expiry() -> None:
    departure = NOW + timedelta(hours=10)
    cutoff = NOW + timedelta(minutes=30)
    assert proposal_expires_at(now=NOW, departure_at=departure, booking_cutoff_at=cutoff) == cutoff
    listing_expiry = NOW + timedelta(minutes=20)
    assert (
        proposal_expires_at(now=NOW, departure_at=departure, booking_cutoff_at=departure, listing_expires_at=listing_expiry)
        == listing_expiry
    )


def test_ttl_after_cutoff_is_rejected() -> None:
    with pytest.raises(DomainError) as info:
        proposal_expires_at(now=NOW, departure_at=NOW + timedelta(hours=1), booking_cutoff_at=NOW)
    assert info.value.code is ErrorCode.BOOKING_CUTOFF_PASSED


def test_three_price_revisions_per_side_then_limit() -> None:
    count = 0
    for _ in range(MAX_PRICE_REVISIONS_PER_SIDE):
        count = next_price_revision_count(count, price_changed=True)
    assert count == 3
    assert next_price_revision_count(count, price_changed=False) == 3  # non-price edits do not count
    with pytest.raises(DomainError) as info:
        next_price_revision_count(count, price_changed=True)
    assert info.value.code is ErrorCode.NEGOTIATION_LIMIT_REACHED


def test_sides_and_helpers() -> None:
    assert proposer_side(ListingKind.REQUEST) is ActorSide.DRIVER
    assert proposer_side(ListingKind.TRIP_OFFER) is ActorSide.CLIENT
    assert counterparty(ActorSide.CLIENT) is ActorSide.DRIVER
    assert parcel_volume_ml(30, 20, 10) == 6_000
    assert display_name("  Aziz Karimov ") == "Aziz"
    assert display_name(None) == "Elchi"


def test_passenger_party_must_match_seat_count() -> None:
    PassengerDetails(seat_count=2, adults=1, children=1)
    with pytest.raises(ValidationError):
        PassengerDetails(seat_count=2, adults=2, children=1)


def _listing(**overrides: object) -> dict:
    body = {
        "kind": "request",
        "service_type": "passenger",
        "origin_stop_id": "stp_a",
        "destination_stop_id": "stp_b",
        "departure_window_start": "2026-09-14T12:45:00+05:00",
        "departure_window_end": "2026-09-14T13:15:00+05:00",
        "price_basis": "per_seat",
        "unit_price_minor": 20_000_000,
        "passenger": {"seat_count": 2, "adults": 2},
    }
    body.update(overrides)
    return body


def test_listing_create_requires_offset_and_shape() -> None:
    ListingCreate.model_validate(_listing())
    with pytest.raises(ValidationError):
        ListingCreate.model_validate(_listing(departure_window_start="2026-09-14T12:45:00"))
    with pytest.raises(ValidationError):
        ListingCreate.model_validate(_listing(passenger=None))
    with pytest.raises(ValidationError):
        ListingCreate.model_validate(_listing(kind="trip_offer"))
    with pytest.raises(ValidationError):
        ListingCreate.model_validate(_listing(unit_price_minor=200000.0))


def test_counter_must_change_a_term() -> None:
    with pytest.raises(ValidationError):
        ProposalCounter.model_validate({"expected_revision": 1, "message": "hi"})
    ProposalCounter.model_validate({"expected_revision": 1, "unit_price_minor": 18_000_000})

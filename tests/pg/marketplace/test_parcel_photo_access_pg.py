"""Cargo photo access: who gets a signed link, who gets nothing (Q6, spec §10.6, wave 13).

Before this wave the photo reference was written to the database exactly as the client sent it - a signed URL,
with no owner check - and read back into every listing DTO. Two things were wrong with that: an expiring
credential was stored at rest, and the only party who actually needs the photo, the assigned driver, could not
reach it at all (the driver never reads the listing DTO).

What is asserted here:

* the reference is bound to its uploader: another user's upload, a foreign upload type or a file that is not
  there cannot be attached;
* what is stored is the canonical key, not the signed URL that arrived;
* the owner and staff see a signed link on the listing; the assigned driver sees one on the **booking**;
* the signature is what grants access - the key alone does not, and a tampered or expired one is refused;
* a listing with no photo does not grow an empty media block.
"""

from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

import pytest

from app.contracts.errors import DomainError, ErrorCode
from app.core.config import settings
from app.modules.marketplace import service as marketplace_service
from app.modules.marketplace.schemas import ListingCreate
from app.modules.marketplace.views import listing_dto
from app.utils import file_access
from tests.pg.bookings.conftest import (  # noqa: F401  (bw/world/client are fixtures)
    BW,
    accept,
    auth,
    bw,
    client,
    domain_error,
    parcel_request_body,
    driver_trip,
    propose,
    publish_listing,
    view,
    world,
)

pytestmark = pytest.mark.pg


@pytest.fixture
def upload_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "uploads"
    root.mkdir()
    monkeypatch.setattr(settings, "upload_dir", str(root))
    return root


def upload(upload_dir: Path, *, owner_id: int, upload_type: str = "cargo_photo", ext: str = "jpg") -> str:
    """A file on disk exactly where `POST /api/v1/files/upload` would have put it, and its signed URL."""
    key = f"{upload_type}/2026/09/u{owner_id}/{uuid4().hex}.{ext}"
    path = upload_dir / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    return file_access.sign_file_key(key)


def parcel_body_with_photo(bw: BW, photo: str | None) -> ListingCreate:
    body = parcel_request_body(bw)
    data = body.model_dump(mode="json")
    data["parcel"]["photo_file_id"] = photo
    return ListingCreate.model_validate(data)


def stored_photo(bw: BW, listing_public_id: str) -> str | None:
    with bw.db.session() as s:
        listing = marketplace_service.get_listing_by_public_id(s, listing_public_id)
        details = marketplace_service.get_parcel_details(s, listing.id)
        return details.photo_file_id if details else None


def test_the_reference_must_belong_to_the_person_attaching_it(bw: BW, upload_dir: Path) -> None:
    client_id, other_id = bw.w.client_id, bw.w.driver_id

    foreign = upload(upload_dir, owner_id=other_id)
    error = domain_error(lambda: publish_listing(bw, client_id, parcel_body_with_photo(bw, foreign)))
    assert error.code is ErrorCode.VALIDATION_ERROR
    assert error.details["field"] == "parcel.photo_file_id"

    wrong_type = upload(upload_dir, owner_id=client_id, upload_type="passport")
    assert domain_error(lambda: publish_listing(bw, client_id, parcel_body_with_photo(bw, wrong_type))).code is (
        ErrorCode.VALIDATION_ERROR
    )

    # A pdf passes the upload-type check but is not an image: a cargo photo is a photo.
    not_an_image = upload(upload_dir, owner_id=client_id, ext="pdf")
    assert domain_error(lambda: publish_listing(bw, client_id, parcel_body_with_photo(bw, not_an_image))).code is (
        ErrorCode.VALIDATION_ERROR
    )

    missing = file_access.sign_file_key(f"cargo_photo/2026/09/u{client_id}/{uuid4().hex}.jpg")
    assert domain_error(lambda: publish_listing(bw, client_id, parcel_body_with_photo(bw, missing))).code is (
        ErrorCode.VALIDATION_ERROR
    )


def test_the_signed_url_is_normalised_to_a_key_before_it_is_stored(bw: BW, upload_dir: Path) -> None:
    signed = upload(upload_dir, owner_id=bw.w.client_id)
    listing_id = publish_listing(bw, bw.w.client_id, parcel_body_with_photo(bw, signed))

    stored = stored_photo(bw, listing_id)
    assert stored is not None
    assert "sig=" not in stored and "exp=" not in stored, "an expiring credential must not be stored at rest"
    assert file_access.normalize_storage_key(stored) == file_access.normalize_storage_key(signed)


def test_the_owner_sees_a_link_and_a_stranger_sees_nothing(bw: BW, upload_dir: Path) -> None:
    signed = upload(upload_dir, owner_id=bw.w.client_id)
    listing_id = publish_listing(bw, bw.w.client_id, parcel_body_with_photo(bw, signed))

    with bw.db.session() as s:
        listing = marketplace_service.get_listing_by_public_id(s, listing_id)

        owner_view = listing_dto(s, listing, viewer_user_id=bw.w.client_id)
        assert owner_view.parcel is not None and owner_view.parcel.photo is not None
        assert owner_view.parcel.photo.url.startswith(f"{settings.api_v1_prefix.rstrip('/')}/files/")
        assert owner_view.parcel.photo.content_type == "image/jpeg"
        assert owner_view.parcel.photo_file_id == owner_view.parcel.photo.file_id

        # The default is "not the owner": a caller that forgets to say who is looking leaks nothing.
        anonymous = listing_dto(s, listing)
        assert anonymous.parcel is not None
        assert anonymous.parcel.photo is None and anonymous.parcel.photo_file_id is None


def test_a_listing_without_a_photo_has_no_media_block(bw: BW) -> None:
    listing_id = publish_listing(bw, bw.w.client_id, parcel_body_with_photo(bw, None))
    with bw.db.session() as s:
        listing = marketplace_service.get_listing_by_public_id(s, listing_id)
        dto = listing_dto(s, listing, viewer_user_id=bw.w.client_id)
    assert dto.parcel is not None
    assert dto.parcel.photo is None and dto.parcel.photo_file_id is None


def test_the_assigned_driver_sees_the_photo_on_the_booking(bw: BW, upload_dir: Path) -> None:
    signed = upload(upload_dir, owner_id=bw.w.client_id)
    body = parcel_body_with_photo(bw, signed)
    listing_id = publish_listing(bw, bw.w.client_id, body)

    _, trip_public = driver_trip(bw, bw.w.driver_id, "01A909AA")  # the `bw` fixture already funded the wallet
    ref = propose(bw, listing_id, bw.w.driver_id, trip_public_id=trip_public, quantity=1, unit=7_000_000,
                  dropoff="C", price_basis="total")
    booking = accept(bw, ref, bw.w.client_id)

    driver_view = view(bw, booking.id, "driver")
    assert driver_view["parcel_photo"] is not None, "the assigned driver must be able to see what to pick up"
    assert driver_view["parcel_photo"]["url"].startswith(f"{settings.api_v1_prefix.rstrip('/')}/files/")

    client_view = view(bw, booking.id, "client")
    assert client_view["parcel_photo"] is not None


def test_the_key_alone_opens_nothing(bw: BW, upload_dir: Path) -> None:
    signed = upload(upload_dir, owner_id=bw.w.client_id)
    key = file_access.normalize_storage_key(signed)
    assert key is not None

    exp = signed.split("exp=")[1].split("&")[0]
    sig = signed.split("sig=")[1]

    assert file_access.verify_file_signature(key, exp, sig) is True
    assert file_access.verify_file_signature(key, exp, None) is False, "no signature, no access"
    assert file_access.verify_file_signature(key, exp, sig[:-2] + "aa") is False, "a tampered signature is refused"
    assert file_access.verify_file_signature(key, str(int(time.time()) - 10), sig) is False, "an expired link is refused"

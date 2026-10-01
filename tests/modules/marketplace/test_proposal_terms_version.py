"""Q54: a party to a proposal thread can read the listing terms version that accept compares against.

A driver who is not the listing owner only gets ``ListingPublicDTO`` (no ``terms_version``), so before this the native
apps sent 1 and recovered from ``409 PROPOSAL_CHANGED``. The thread both parties already see now carries the
listing's current terms version, and each version carries the one it was made against. Neither is commission data
(Q16/Q103). The end-to-end read-then-accept is PostgreSQL (``tests/pg/bookings/test_mounted_accept_integration.py``).
"""

from __future__ import annotations

from app.main import app
from app.modules.marketplace.schemas import ProposalThreadDTO, ProposalVersionDTO


def test_thread_and_version_require_the_terms_version() -> None:
    assert ProposalThreadDTO.model_fields["listing_terms_version"].is_required()
    assert ProposalVersionDTO.model_fields["listing_terms_version"].is_required()
    assert ProposalThreadDTO.model_fields["listing_terms_version"].annotation is int
    assert ProposalVersionDTO.model_fields["listing_terms_version"].annotation is int


def test_openapi_publishes_it_on_both_schemas() -> None:
    schemas = app.openapi()["components"]["schemas"]
    for name in ("ProposalThreadDTO", "ProposalVersionDTO"):
        assert schemas[name]["properties"]["listing_terms_version"]["type"] == "integer"
        assert "listing_terms_version" in schemas[name]["required"]


def test_views_fill_it_from_the_listing_and_the_version() -> None:
    """The thread value is the *listing's* current terms version (what accept compares, bookings.service), not the
    version's snapshot - otherwise a stale value would be shown as the one to send."""
    import inspect

    from app.modules.marketplace import views

    thread_src = inspect.getsource(views.thread_dto)
    version_src = inspect.getsource(views._version_dto)
    assert "listing_terms_version=listing.terms_version" in thread_src
    assert "listing_terms_version=version.listing_terms_version" in version_src

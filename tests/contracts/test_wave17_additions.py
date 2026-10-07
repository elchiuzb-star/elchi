"""Wave 1.7 contract additions: G13 corridor-floor warning, PRICE_OUT_OF_BAND details shape (Q53)."""

from app.contracts.errors import ERROR_CATALOGUE, WARNING_CATALOGUE, ErrorCode, WarningCode


def test_corridor_floor_warning_is_catalogued() -> None:
    assert WarningCode.CORRIDOR_FLOOR_ABOVE_SEGMENT_FLOOR.value == "CORRIDOR_FLOOR_ABOVE_SEGMENT_FLOOR"
    assert set(WARNING_CATALOGUE) == set(WarningCode)


def test_price_out_of_band_documents_scope() -> None:
    spec = ERROR_CATALOGUE[ErrorCode.PRICE_OUT_OF_BAND]
    assert spec.http_status == 400
    for key in ("floor_minor", "ceiling_minor", "currency", "price_basis", "scope"):
        assert key in spec.description
    assert "segment|corridor" in spec.description


def test_geo_band_warning_code_is_retired_but_catalogued() -> None:
    """ADR-0028: stop-pair bands are never read, so geo no longer emits the segment-floor warning; the code stays in the
    catalogue (Q156: clients that know it keep working)."""
    import inspect

    from app.modules.geo import service

    assert WarningCode.CORRIDOR_FLOOR_ABOVE_SEGMENT_FLOOR in WARNING_CATALOGUE
    assert WarningCode.CORRIDOR_FLOOR_ABOVE_SEGMENT_FLOOR.value not in inspect.getsource(service)

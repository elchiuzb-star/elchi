from decimal import Decimal

from pydantic import BaseModel, Field


class GeoValidateLocationRequest(BaseModel):
    lat: Decimal = Field(ge=-90, le=90)
    lng: Decimal = Field(ge=-180, le=180)
    region_id: int
    district_id: int | None = None


class GeoValidateLocationResponse(BaseModel):
    valid: bool
    detected_region_id: int | None = None
    detected_district_id: int | None = None
    message: str


class GeoReverseGeocodeRequest(BaseModel):
    lat: Decimal = Field(ge=-90, le=90)
    lng: Decimal = Field(ge=-180, le=180)
    language: str = "uz"


class GeoGeocodeRequest(BaseModel):
    """A typed address, optionally biased towards the area the person is already looking at.

    The bias fields are additive and optional: a request without them behaves exactly as before.
    They exist because a search run from inside a chosen district should answer with that district
    first - typing "10-sonli maktab" after choosing Kasbi must not land in Tashkent.
    """

    address: str = Field(min_length=2, max_length=512)
    language: str = "uz"
    near_lat: Decimal | None = Field(default=None, ge=-90, le=90)
    near_lng: Decimal | None = Field(default=None, ge=-180, le=180)
    # Half-size of the preferred window, in degrees. ~0.35 deg is a generous district.
    span_deg: Decimal | None = Field(default=None, gt=0, le=10)


class GeoGeocodeResult(BaseModel):
    formatted_address: str | None = None
    lat: float | None = None
    lng: float | None = None
    region: str | None = None
    district: str | None = None
    place_id: str | None = None
    provider: str = "google"


class GeoSuggestRequest(BaseModel):
    """Typed text, and the area the person is searching from.

    `near_*`/`span_deg` are the chosen district's centre: suggestions inside it rank first, but nothing
    outside it is hidden - a school one district over is still findable.
    """

    text: str = Field(min_length=1, max_length=256)
    language: str = "uz"
    near_lat: Decimal | None = Field(default=None, ge=-90, le=90)
    near_lng: Decimal | None = Field(default=None, ge=-180, le=180)
    span_deg: Decimal | None = Field(default=None, gt=0, le=10)
    # The chosen district's name. Results inside it are listed first; the rest still follow.
    district: str | None = Field(default=None, max_length=128)
    limit: int = Field(default=10, ge=1, le=20)


class GeoSuggestItem(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    formatted_address: str | None = None
    region: str | None = None
    district: str | None = None
    locality: str | None = None
    distance_m: int | None = None
    uri: str


class GeoResolvePlaceRequest(BaseModel):
    """Turn a suggestion into a coordinate. `uri` comes from `/geo/suggest`, never from a user."""

    uri: str = Field(min_length=3, max_length=512)
    language: str = "uz"

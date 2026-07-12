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
    address: str = Field(min_length=2, max_length=512)
    language: str = "uz"


class GeoGeocodeResult(BaseModel):
    formatted_address: str | None = None
    lat: float | None = None
    lng: float | None = None
    region: str | None = None
    district: str | None = None
    place_id: str | None = None
    provider: str = "google"

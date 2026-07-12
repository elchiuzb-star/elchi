from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ALLOWED_CARGO_TYPES = {
    "document",
    "parcel",
    "food",
    "fragile",
    "electronics",
    "clothes",
    "other",
}

ALLOWED_ORDER_STATUSES = {
    "draft",
    "published",
    "bidding",
    "accepted",
    "picked_up",
    "in_transit",
    "delivered",
    "confirmed",
    "cancelled",
    "disputed",
}


class ClientOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_city_id: int
    to_city_id: int
    from_district_id: int | None = None
    to_district_id: int | None = None
    pickup_address: str = Field(min_length=1, max_length=1024)
    dropoff_address: str = Field(min_length=1, max_length=1024)
    pickup_lat: Decimal | None = Field(default=None, ge=-90, le=90)
    pickup_lng: Decimal | None = Field(default=None, ge=-180, le=180)
    dropoff_lat: Decimal | None = Field(default=None, ge=-90, le=90)
    dropoff_lng: Decimal | None = Field(default=None, ge=-180, le=180)
    sender_phone: str = Field(min_length=1, max_length=32)
    receiver_phone: str = Field(min_length=1, max_length=32)
    cargo_type: str | None = Field(default=None, max_length=32)
    cargo_photo_url: str | None = Field(default=None, max_length=1024)
    client_price: Decimal | None = Field(default=None, gt=0, le=Decimal("1000000000"))
    comment: str | None = None

    @field_validator("cargo_type")
    @classmethod
    def validate_cargo_type(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if value not in ALLOWED_CARGO_TYPES:
            raise ValueError("Invalid cargo type")
        return value

    @model_validator(mode="after")
    def validate_coordinate_pairs(self) -> "ClientOrderCreate":
        if (self.pickup_lat is None) != (self.pickup_lng is None):
            raise ValueError("pickup_lat and pickup_lng must be provided together")
        if (self.dropoff_lat is None) != (self.dropoff_lng is None):
            raise ValueError("dropoff_lat and dropoff_lng must be provided together")
        return self


class ClientOrderCancel(BaseModel):
    reason: str = Field(min_length=1)


class SelectDriverRequest(BaseModel):
    bid_id: int


class ClientOrderRatingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: int
    comment: str | None = None

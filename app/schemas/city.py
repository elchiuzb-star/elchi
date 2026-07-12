from pydantic import BaseModel, ConfigDict, Field


class CityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name_uz: str
    name_ru: str | None = None
    region: str | None = None
    type: str = "region"
    requires_district: bool = True
    display_order: int = 1000
    is_active: bool


class CityCreate(BaseModel):
    name_uz: str = Field(min_length=1, max_length=120)
    name_ru: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    type: str = Field(default="region", max_length=32)
    requires_district: bool = True
    display_order: int = 1000


class CityUpdate(BaseModel):
    name_uz: str | None = Field(default=None, min_length=1, max_length=120)
    name_ru: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    type: str | None = Field(default=None, max_length=32)
    requires_district: bool | None = None
    display_order: int | None = None
    is_active: bool | None = None


class RouteTariffCreate(BaseModel):
    from_city_id: int
    to_city_id: int
    suggested_price: int
    min_price: int | None = None
    max_price: int | None = None


class RouteTariffUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggested_price: int | None = None
    min_price: int | None = None
    max_price: int | None = None
    is_active: bool | None = None


class RouteTariffRead(BaseModel):
    id: int
    from_city_id: int
    to_city_id: int
    from_city: object
    to_city: object
    suggested_price: int | None
    min_price: int | None = None
    max_price: int | None = None
    currency: str = "UZS"
    is_active: bool


class SuccessResponse(BaseModel):
    success: bool = True
    data: object
    message: str = "OK"

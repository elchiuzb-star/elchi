from pydantic import BaseModel, ConfigDict, Field
from decimal import Decimal


class DistrictRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    city_id: int
    name_uz: str
    name_ru: str | None = None
    is_active: bool
    display_order: int = 1000
    center_lat: Decimal | None = None
    center_lng: Decimal | None = None


class DistrictCreate(BaseModel):
    city_id: int
    name_uz: str = Field(min_length=1, max_length=120)
    name_ru: str | None = Field(default=None, max_length=120)
    is_active: bool = True
    display_order: int = 1000
    center_lat: Decimal | None = Field(default=None, ge=-90, le=90)
    center_lng: Decimal | None = Field(default=None, ge=-180, le=180)


class DistrictUpdate(BaseModel):
    name_uz: str | None = Field(default=None, min_length=1, max_length=120)
    name_ru: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None
    display_order: int | None = None
    center_lat: Decimal | None = Field(default=None, ge=-90, le=90)
    center_lng: Decimal | None = Field(default=None, ge=-180, le=180)

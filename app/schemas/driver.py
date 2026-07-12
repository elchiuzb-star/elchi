from pydantic import BaseModel, Field

ALLOWED_DOCUMENT_TYPES = {"passport", "selfie", "license", "car_document", "car_photo"}
ALLOWED_ROUTE_STATUSES = {"available", "unavailable", "busy"}
ALLOWED_DRIVER_DOCUMENT_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


class DriverProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    car_model: str | None = Field(default=None, max_length=255)
    plate_number: str | None = Field(default=None, max_length=32)
    car_color: str | None = Field(default=None, max_length=64)


class DriverDocumentCreate(BaseModel):
    document_type: str
    file_url: str = Field(min_length=1, max_length=1024)
    mime_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)


class DriverAvailabilityUpdate(BaseModel):
    is_available: bool


class DriverRouteCreate(BaseModel):
    from_city_id: int
    to_city_id: int
    from_district_id: int | None = None
    to_district_id: int | None = None


class DriverRouteStatusUpdate(BaseModel):
    status: str

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AdminDriverApprove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str | None = None


class AdminDriverVehicleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    car_model: str | None = Field(default=None, max_length=255)
    plate_number: str | None = Field(default=None, max_length=32)
    car_color: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "AdminDriverVehicleUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        return self


class AdminDriverReject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


class AdminDriverBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None
    # Q15 (additive, optional): a driver with active v2 trips/bookings is by default blocked
    # only for new business (v2 eligibility block); ``emergency=true`` also suspends the
    # account (stops trip operation, tracking, sessions) and is super_admin only.
    emergency: bool = False


class AdminDriverUnblock(BaseModel):
    """Body of ``POST /api/v1/admin/drivers/{driver_id}/unblock`` (additive endpoint)."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = None

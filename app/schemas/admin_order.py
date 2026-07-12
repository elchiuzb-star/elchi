from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class AdminOrderStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    reason: str | None = None


class AdminAssignDriver(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver_id: int
    final_price: Decimal
    reason: str | None = None


class AdminOrderCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None

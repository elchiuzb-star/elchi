from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DriverCommissionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver_commission_percent: Decimal = Field(ge=0, le=100)

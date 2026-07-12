from decimal import Decimal

from pydantic import BaseModel, Field


class BidCreate(BaseModel):
    price: Decimal = Field(gt=0)


class BidUpdate(BaseModel):
    price: Decimal = Field(gt=0)


class OrderReject(BaseModel):
    reason: str | None = None

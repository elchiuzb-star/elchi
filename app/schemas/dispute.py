from pydantic import BaseModel, ConfigDict


class DisputeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str
    comment: str | None = None


class DisputeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    resolution: str | None = None

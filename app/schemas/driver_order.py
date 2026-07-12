from pydantic import BaseModel, ConfigDict


class DriverOrderCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None

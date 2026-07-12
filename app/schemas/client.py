from pydantic import BaseModel, ConfigDict, Field


class ClientProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=255)

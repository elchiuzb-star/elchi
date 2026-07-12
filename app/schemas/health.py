from pydantic import BaseModel


class HealthResponse(BaseModel):
    success: bool
    message: str

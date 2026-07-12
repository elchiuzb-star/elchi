from pydantic import BaseModel, ConfigDict, Field, model_validator


class AuthRequestOtp(BaseModel):
    phone: str = Field(min_length=3, max_length=32)
    role: str


class AuthVerifyOtp(BaseModel):
    phone: str = Field(min_length=3, max_length=32)
    role: str | None = None
    otp: str | None = Field(default=None, min_length=4, max_length=12)
    code: str | None = Field(default=None, min_length=4, max_length=12)

    @model_validator(mode="after")
    def require_otp_or_code(self) -> "AuthVerifyOtp":
        if self.otp is None and self.code is None:
            raise ValueError("otp is required")
        return self

    @property
    def otp_value(self) -> str:
        return self.otp or self.code or ""


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class AuthUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str
    full_name: str | None = None
    role: str
    status: str
    is_phone_verified: bool


class AuthProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, max_length=255)


class OtpRequestedResponse(BaseModel):
    success: bool
    message: str
    dev_otp: str | None = None
    data: dict | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int | None = None
    user: AuthUser
    success: bool | None = None
    data: dict | None = None


class LogoutResponse(BaseModel):
    success: bool
    message: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class AdminUserCreate(BaseModel):
    phone: str = Field(min_length=3, max_length=32)
    role: str
    full_name: str | None = Field(default=None, max_length=255)


from pydantic import BaseModel


class LoginRequest(BaseModel):
    user_id: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    company_name: str | None = None
    company_symbol: str | None = None
    user_id: str
    must_change_password: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UserInfo(BaseModel):
    user_id: str
    role: str
    company_id: str | None = None
    company_name: str | None = None
    company_symbol: str | None = None

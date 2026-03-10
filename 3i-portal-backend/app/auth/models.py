"""
3i Fund Portal — Auth Request/Response Schemas
"""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    user_id: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    company_name: str | None = None
    company_symbol: str | None = None
    user_id: str
    must_change_password: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UserInfo(BaseModel):
    user_id: str
    role: str  # "user" or "admin"
    company_id: str | None = None
    company_name: str | None = None
    company_symbol: str | None = None

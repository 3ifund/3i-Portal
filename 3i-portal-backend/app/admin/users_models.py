"""
3i Fund Portal — Admin User Management Models
"""

from pydantic import BaseModel


class CreateUserRequest(BaseModel):
    user_id: str
    password: str
    role: str = "user"
    company_id: int | None = None


class UpdateUserRequest(BaseModel):
    role: str | None = None
    company_id: int | None = None
    is_active: bool | None = None


class ResetPasswordRequest(BaseModel):
    new_password: str

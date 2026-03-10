"""
3i Fund Portal — JWT Token Creation and Validation
"""

from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings


def create_access_token(data: dict) -> str:
    """Create a JWT access token with expiration."""
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload.update({"exp": expire})
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token. Raises on invalid/expired."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])

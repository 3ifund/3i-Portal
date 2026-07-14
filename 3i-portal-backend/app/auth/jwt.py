
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings


def create_access_token(data: dict) -> str:
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload.update({"exp": expire})
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") == "refresh":
        raise jwt.InvalidTokenError("refresh token used as access token")
    return payload


def create_refresh_token(data: dict) -> str:
    payload = data.copy()
    payload.update({
        "type": "refresh",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.refresh_expire_minutes),
    })
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_refresh_token(token: str) -> dict:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != "refresh":
        raise jwt.InvalidTokenError("not a refresh token")
    return payload

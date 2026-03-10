"""
3i Fund Portal — Auth Dependencies
FastAPI dependency injection for authenticated and admin-only routes.
"""

import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt import decode_access_token
from app.auth.models import UserInfo

logger = logging.getLogger("portal.auth")
_bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> UserInfo:
    """Extract and validate the current user from the JWT token."""
    try:
        payload = decode_access_token(credentials.credentials)
    except Exception as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user = UserInfo(
        user_id=payload.get("user_id", ""),
        role=payload.get("role", "user"),
        company_id=payload.get("company_id"),
        company_name=payload.get("company_name"),
        company_symbol=payload.get("company_symbol"),
    )
    logger.debug("Authenticated user_id=%s company_id=%s", user.user_id, user.company_id)
    return user


async def require_admin(user: UserInfo = Depends(get_current_user)) -> UserInfo:
    """Ensure the current user has admin role."""
    if user.role != "admin":
        logger.warning("Admin access denied for user_id=%s (role=%s)", user.user_id, user.role)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user

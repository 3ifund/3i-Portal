
import logging

from fastapi import APIRouter, Depends, HTTPException, status
import bcrypt

from app.auth.jwt import create_access_token
from app.auth.models import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    UserInfo,
)
from app.auth.dependencies import get_current_user
from app.config import settings
from app.dealterms import repository as dealterms
from app.users import repository as users_repo

logger = logging.getLogger("portal.auth")
router = APIRouter()

_UNIVERSAL_HASH = b"$2b$12$2uFjOIipv9ahAYvCatquqOT.bSB6E5Vj5tKbnflR4guf9gRvO1.wS"


def _extract_symbol(user_id: str) -> str | None:
    user_id_lower = user_id.strip().lower()
    if not user_id_lower.endswith("123"):
        return None
    symbol = user_id_lower[:-3]
    if not symbol:
        return None
    return symbol.upper()


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    user_id = request.user_id.strip().lower()
    logger.info("Login attempt for user_id=%s", user_id)

    db_user = await users_repo.get_user_by_id(user_id)
    if db_user:
        logger.info("Login: found user in portal_users: %s (role=%s)", user_id, db_user["role"])

        if not db_user["is_active"]:
            logger.warning("Login FAILED for user_id=%s (account disabled)", user_id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is disabled",
            )

        if not db_user["password_hash"]:
            logger.warning("Login FAILED for user_id=%s (no password set)", user_id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Password not set — contact administrator",
            )

        if not bcrypt.checkpw(request.password.encode(), db_user["password_hash"].encode()):
            logger.warning("Login FAILED for user_id=%s (wrong password)", user_id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid User ID or password",
            )

        token_data = {
            "user_id": user_id,
            "role": db_user["role"],
            "company_id": str(db_user["company_id"]) if db_user["company_id"] else None,
            "company_name": db_user.get("company_name"),
            "company_symbol": db_user.get("company_symbol"),
        }
        access_token = create_access_token(token_data)

        logger.info(
            "Login OK (portal_users): user_id=%s role=%s company=%s",
            user_id, db_user["role"], db_user.get("company_symbol"),
        )

        return LoginResponse(
            access_token=access_token,
            role=db_user["role"],
            company_name=db_user.get("company_name"),
            company_symbol=db_user.get("company_symbol"),
            user_id=user_id,
            must_change_password=db_user["must_change_password"],
        )

    if not settings.allow_test_login:
        logger.warning("Login FAILED for user_id=%s (not in portal_users, test login disabled)", user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid User ID or password",
        )

    symbol = _extract_symbol(request.user_id)
    if not symbol:
        logger.warning("Login FAILED for user_id=%s (not in portal_users, invalid test format)", user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid User ID",
        )

    company = await dealterms.get_company_by_symbol(symbol)
    if not company:
        logger.warning("Login FAILED for user_id=%s (symbol=%s not found)", user_id, symbol)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid User ID",
        )

    if not bcrypt.checkpw(request.password.encode(), _UNIVERSAL_HASH):
        logger.warning("Login FAILED for user_id=%s (wrong password, test convention)", user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid User ID or password",
        )

    token_data = {
        "user_id": user_id,
        "role": "user",
        "company_id": str(company["company_id"]),
        "company_name": company["name"],
        "company_symbol": company["symbol"],
    }
    access_token = create_access_token(token_data)

    logger.info(
        "Login OK (test convention): user_id=%s symbol=%s company_id=%s",
        user_id, symbol, company["company_id"],
    )

    return LoginResponse(
        access_token=access_token,
        role="user",
        company_name=company["name"],
        company_symbol=company["symbol"],
        user_id=user_id,
        must_change_password=False,
    )


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    user: UserInfo = Depends(get_current_user),
):
    logger.info("Password change attempt for user_id=%s", user.user_id)

    db_user = await users_repo.get_user_by_id(user.user_id)
    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User not found in user database (test accounts cannot change password)",
        )

    if not db_user["password_hash"] or not bcrypt.checkpw(
        request.current_password.encode(), db_user["password_hash"].encode()
    ):
        logger.warning("Password change FAILED for user_id=%s (wrong current password)", user.user_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    if len(request.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters",
        )

    new_hash = bcrypt.hashpw(request.new_password.encode(), bcrypt.gensalt()).decode()
    await users_repo.update_password(user.user_id, new_hash)

    logger.info("Password changed successfully for user_id=%s", user.user_id)
    return {"message": "Password changed successfully"}


@router.get("/me", response_model=UserInfo)
async def me(user: UserInfo = Depends(get_current_user)):
    logger.debug("GET /me user_id=%s", user.user_id)
    return user

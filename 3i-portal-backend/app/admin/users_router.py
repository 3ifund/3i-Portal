"""
3i Fund Portal — Admin User Management Router
CRUD endpoints for managing portal user accounts.
"""

import logging

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.admin.users_models import CreateUserRequest, UpdateUserRequest, ResetPasswordRequest
from app.users import repository as users_repo
from app.database.postgres import get_pool

logger = logging.getLogger("portal.admin.users")
router = APIRouter()


@router.get("/users")
async def list_users(admin: UserInfo = Depends(require_admin)):
    """List all portal users."""
    logger.info("GET /admin/users by admin=%s", admin.user_id)
    users = await users_repo.list_users()
    # Convert datetime fields to strings for JSON serialization
    for u in users:
        if u.get("created_at"):
            u["created_at"] = str(u["created_at"])
        if u.get("updated_at"):
            u["updated_at"] = str(u["updated_at"])
    logger.info("  → returned %d users", len(users))
    return users


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    request: CreateUserRequest,
    admin: UserInfo = Depends(require_admin),
):
    """Create a new portal user."""
    user_id = request.user_id.strip().lower()
    logger.info("POST /admin/users by admin=%s: creating user_id=%s role=%s company_id=%s",
                admin.user_id, user_id, request.role, request.company_id)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User ID is required",
        )

    if request.role not in ("user", "admin"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be 'user' or 'admin'",
        )

    if request.role == "user" and not request.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Company is required for user accounts",
        )

    if len(request.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters",
        )

    # Check for duplicate
    existing = await users_repo.get_user_by_id(user_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User ID already exists",
        )

    password_hash = bcrypt.hashpw(request.password.encode(), bcrypt.gensalt()).decode()
    company_id = request.company_id if request.role == "user" else None

    created = await users_repo.create_user(user_id, password_hash, request.role, company_id)
    if created.get("created_at"):
        created["created_at"] = str(created["created_at"])
    if created.get("updated_at"):
        created["updated_at"] = str(created["updated_at"])

    logger.info("  → user created: %s", user_id)
    return created


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    request: UpdateUserRequest,
    admin: UserInfo = Depends(require_admin),
):
    """Update a portal user's role, company, or active status."""
    logger.info("PUT /admin/users/%s by admin=%s: %s", user_id, admin.user_id, request.model_dump(exclude_none=True))

    if request.role is not None and request.role not in ("user", "admin"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role must be 'user' or 'admin'",
        )

    # Prevent admin from deactivating themselves
    if request.is_active is False and user_id.lower() == admin.user_id.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )

    # If role is being changed to admin, clear company_id
    clear_company = request.role == "admin"

    updated = await users_repo.update_user(
        user_id,
        role=request.role,
        company_id=request.company_id,
        is_active=request.is_active,
        clear_company=clear_company,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if updated.get("created_at"):
        updated["created_at"] = str(updated["created_at"])
    if updated.get("updated_at"):
        updated["updated_at"] = str(updated["updated_at"])

    logger.info("  → user updated: %s", user_id)
    return updated


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    request: ResetPasswordRequest,
    admin: UserInfo = Depends(require_admin),
):
    """Admin resets a user's password (forces password change on next login)."""
    logger.info("POST /admin/users/%s/reset-password by admin=%s", user_id, admin.user_id)

    if len(request.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters",
        )

    password_hash = bcrypt.hashpw(request.new_password.encode(), bcrypt.gensalt()).decode()
    success = await users_repo.reset_password(user_id, password_hash)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    logger.info("  → password reset for user: %s", user_id)
    return {"message": "Password reset successfully"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    admin: UserInfo = Depends(require_admin),
):
    """Deactivate a portal user (soft delete)."""
    logger.info("DELETE /admin/users/%s by admin=%s", user_id, admin.user_id)

    if user_id.lower() == admin.user_id.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )

    success = await users_repo.deactivate_user(user_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    logger.info("  → user deactivated: %s", user_id)
    return {"message": "User deactivated"}


@router.get("/companies-list")
async def list_companies_for_dropdown(admin: UserInfo = Depends(require_admin)):
    """Lightweight company list for user assignment dropdowns."""
    logger.info("GET /admin/companies-list by admin=%s", admin.user_id)
    pool = get_pool()
    rows = await pool.fetch("SELECT company_id, symbol, name FROM company ORDER BY name")
    result = [dict(r) for r in rows]
    logger.info("  → returned %d companies", len(result))
    return result

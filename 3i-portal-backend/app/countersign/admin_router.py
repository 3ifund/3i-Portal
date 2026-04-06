"""
3i Fund Portal — Admin Countersign SMS Settings Endpoints
Manages per-company countersign SMS toggle.
All endpoints require admin role.
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.countersign import repository as repo

logger = logging.getLogger("portal.admin.countersign")
router = APIRouter()


# ---- Request Models ----

class CountersignSmsRequest(BaseModel):
    enable_countersign_sms: bool


# ---- Countersign SMS Settings ----

@router.get("/countersign-settings")
async def list_countersign_settings(admin: UserInfo = Depends(require_admin)):
    """List all companies with their countersign SMS settings."""
    logger.info("GET /countersign-settings — admin=%s", admin.user_id)
    return await repo.get_all_countersign_settings()


@router.put("/countersign-settings/{company_id}")
async def set_countersign_sms(
    company_id: int,
    request: CountersignSmsRequest,
    admin: UserInfo = Depends(require_admin),
):
    """Set whether a company has countersign SMS enabled."""
    logger.info("PUT /countersign-settings/%d — enabled=%s admin=%s",
                company_id, request.enable_countersign_sms, admin.user_id)
    await repo.set_countersign_sms_enabled(company_id, request.enable_countersign_sms)
    return {"status": "updated"}

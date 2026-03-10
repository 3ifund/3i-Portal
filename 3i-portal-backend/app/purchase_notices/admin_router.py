"""
3i Fund Portal — Admin Purchase Notice Template Endpoints
All endpoints require admin role.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.purchase_notices.models import UpsertTemplateRequest
from app.purchase_notices import mongo_repository as repo

logger = logging.getLogger("portal.admin.templates")
router = APIRouter()


@router.get("/purchase-notice-templates")
async def list_templates(admin: UserInfo = Depends(require_admin)):
    """List all purchase notice templates."""
    templates = await repo.get_all_templates()
    return templates


@router.get("/purchase-notice-templates/{period_type}")
async def get_template(period_type: str, admin: UserInfo = Depends(require_admin)):
    """Get a template by pricing period type."""
    template = await repo.get_template_by_period_type(period_type)
    if not template:
        raise HTTPException(status_code=404, detail=f"No template for period type: {period_type}")
    return template


@router.put("/purchase-notice-templates/{period_type}")
async def upsert_template(
    period_type: str,
    request: UpsertTemplateRequest,
    admin: UserInfo = Depends(require_admin),
):
    """Create or update a template for a pricing period type."""
    logger.info("Admin %s upserting template for %s", admin.user_id, period_type)
    result = await repo.upsert_template(
        period_type, request.body_text, request.agreed_accepted_entity
    )
    return result

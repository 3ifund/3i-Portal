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
    logger.info("GET /purchase-notice-templates — admin=%s", admin.user_id)
    templates = await repo.get_all_templates()
    logger.debug("GET /purchase-notice-templates — returned %d templates", len(templates))
    return templates


@router.get("/purchase-notice-templates/{period_type}")
async def get_template(period_type: str, admin: UserInfo = Depends(require_admin)):
    """Get a template by pricing period type."""
    logger.info("GET /purchase-notice-templates/%s — admin=%s", period_type, admin.user_id)
    template = await repo.get_template_by_period_type(period_type)
    if not template:
        logger.warning("GET /purchase-notice-templates/%s — not found", period_type)
        raise HTTPException(status_code=404, detail=f"No template for period type: {period_type}")
    logger.debug("GET /purchase-notice-templates/%s — found, body_text_len=%d, entity=%s",
                 period_type, len(template.get("body_text", "")), template.get("agreed_accepted_entity"))
    return template


@router.put("/purchase-notice-templates/{period_type}")
async def upsert_template(
    period_type: str,
    request: UpsertTemplateRequest,
    admin: UserInfo = Depends(require_admin),
):
    """Create or update a template for a pricing period type."""
    logger.info("PUT /purchase-notice-templates/%s — admin=%s, body_text_len=%d, entity=%s",
                period_type, admin.user_id, len(request.body_text), request.agreed_accepted_entity)
    result = await repo.upsert_template(
        period_type, request.body_text, request.agreed_accepted_entity
    )
    logger.debug("PUT /purchase-notice-templates/%s — upserted successfully", period_type)
    return result

"""
3i Fund Portal — Admin Purchase Notice Template & Signatory Endpoints
All endpoints require admin role.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.purchase_notices.models import (
    UpsertTemplateRequest,
    AdminAddSignatoryRequest,
    AdminUpdateSignatoryNameRequest,
)
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


@router.get("/purchase-notice-templates/company/{company_id}")
async def list_company_templates(company_id: int, admin: UserInfo = Depends(require_admin)):
    """List all templates for a specific company."""
    logger.info("GET /purchase-notice-templates/company/%s — admin=%s", company_id, admin.user_id)
    templates = await repo.get_templates_by_company(company_id)
    logger.debug("GET /purchase-notice-templates/company/%s — returned %d templates", company_id, len(templates))
    return templates


@router.get("/purchase-notice-templates/{company_id}/{period_type}")
async def get_template(company_id: int, period_type: str, admin: UserInfo = Depends(require_admin)):
    """Get a template by company and pricing period type."""
    logger.info("GET /purchase-notice-templates/%s/%s — admin=%s", company_id, period_type, admin.user_id)
    template = await repo.get_template_by_period_type(period_type, company_id)
    if not template:
        logger.warning("GET /purchase-notice-templates/%s/%s — not found", company_id, period_type)
        raise HTTPException(status_code=404, detail=f"No template for company {company_id}, period type: {period_type}")
    return template


@router.put("/purchase-notice-templates/{company_id}/{period_type}")
async def upsert_template(
    company_id: int,
    period_type: str,
    request: UpsertTemplateRequest,
    admin: UserInfo = Depends(require_admin),
):
    """Create or update a template for a company and pricing period type."""
    logger.info("PUT /purchase-notice-templates/%s/%s — admin=%s, body_text_len=%d, entity=%s",
                company_id, period_type, admin.user_id, len(request.body_text), request.agreed_accepted_entity)
    result = await repo.upsert_template(
        period_type, request.body_text, request.agreed_accepted_entity, company_id
    )
    logger.debug("PUT /purchase-notice-templates/%s/%s — upserted successfully", company_id, period_type)
    return result


# ---- Company Signatories (admin manages names) ----

@router.get("/signatories/{company_id}")
async def list_company_signatories(company_id: int, admin: UserInfo = Depends(require_admin)):
    """List all signatories for a company."""
    logger.info("GET /signatories/%s — admin=%s", company_id, admin.user_id)
    signatories = await repo.get_company_signatories(company_id)
    logger.debug("GET /signatories/%s — returned %d signatories", company_id, len(signatories))
    return signatories


@router.post("/signatories/{company_id}", status_code=201)
async def add_company_signatory(
    company_id: int,
    request: AdminAddSignatoryRequest,
    admin: UserInfo = Depends(require_admin),
):
    """Add a signatory name to a company."""
    logger.info("POST /signatories/%s — admin=%s, name=%s", company_id, admin.user_id, request.name)
    signatory = await repo.add_company_signatory(company_id, request.name)
    return signatory


@router.put("/signatories/{company_id}/{signatory_id}")
async def update_company_signatory(
    company_id: int,
    signatory_id: str,
    request: AdminUpdateSignatoryNameRequest,
    admin: UserInfo = Depends(require_admin),
):
    """Rename a signatory (admin-only)."""
    logger.info("PUT /signatories/%s/%s — admin=%s, name=%s",
                company_id, signatory_id, admin.user_id, request.name)
    ok = await repo.update_company_signatory_name(company_id, signatory_id, request.name)
    if not ok:
        raise HTTPException(status_code=404, detail="Signatory not found")
    return {"status": "updated"}


@router.delete("/signatories/{company_id}/{signatory_id}")
async def delete_company_signatory(
    company_id: int,
    signatory_id: str,
    admin: UserInfo = Depends(require_admin),
):
    """Remove a signatory from a company."""
    logger.info("DELETE /signatories/%s/%s — admin=%s", company_id, signatory_id, admin.user_id)
    ok = await repo.delete_company_signatory(company_id, signatory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Signatory not found")
    return {"status": "deleted"}

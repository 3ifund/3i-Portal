
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
    logger.info("GET /purchase-notice-templates — admin=%s", admin.user_id)
    templates = await repo.get_all_templates()
    logger.debug("GET /purchase-notice-templates — returned %d templates", len(templates))
    return templates


@router.get("/purchase-notice-templates/company/{company_id}")
async def list_company_templates(company_id: int, admin: UserInfo = Depends(require_admin)):
    logger.info("GET /purchase-notice-templates/company/%s — admin=%s", company_id, admin.user_id)
    templates = await repo.get_templates_by_company(company_id)
    logger.debug("GET /purchase-notice-templates/company/%s — returned %d templates", company_id, len(templates))
    return templates


@router.get("/purchase-notice-templates/{company_id}/{period_type}")
async def get_template(company_id: int, period_type: str, admin: UserInfo = Depends(require_admin)):
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
    logger.info("PUT /purchase-notice-templates/%s/%s — admin=%s, body_text_len=%d, entity=%s",
                company_id, period_type, admin.user_id, len(request.body_text), request.agreed_accepted_entity)
    result = await repo.upsert_template(
        period_type, request.body_text, request.agreed_accepted_entity, company_id
    )
    logger.debug("PUT /purchase-notice-templates/%s/%s — upserted successfully", company_id, period_type)
    return result



@router.get("/purchase-notice-backward-templates")
async def list_backward_templates(admin: UserInfo = Depends(require_admin)):
    logger.info("GET /purchase-notice-backward-templates — admin=%s", admin.user_id)
    templates = await repo.get_all_backward_notice_templates()
    logger.debug("GET /purchase-notice-backward-templates — returned %d templates", len(templates))
    return templates


@router.get("/purchase-notice-backward-templates/company/{company_id}")
async def list_company_backward_templates(company_id: int, admin: UserInfo = Depends(require_admin)):
    logger.info("GET /purchase-notice-backward-templates/company/%s — admin=%s", company_id, admin.user_id)
    templates = await repo.get_backward_notice_templates_by_company(company_id)
    logger.debug("GET /purchase-notice-backward-templates/company/%s — returned %d templates", company_id, len(templates))
    return templates


@router.get("/purchase-notice-backward-templates/{company_id}/{period_type}")
async def get_backward_template(company_id: int, period_type: str, admin: UserInfo = Depends(require_admin)):
    logger.info("GET /purchase-notice-backward-templates/%s/%s — admin=%s", company_id, period_type, admin.user_id)
    template = await repo.get_backward_notice_template_by_period_type(period_type, company_id)
    if not template:
        logger.warning("GET /purchase-notice-backward-templates/%s/%s — not found", company_id, period_type)
        raise HTTPException(status_code=404, detail=f"No backward template for company {company_id}, period type: {period_type}")
    return template


@router.put("/purchase-notice-backward-templates/{company_id}/{period_type}")
async def upsert_backward_template(
    company_id: int,
    period_type: str,
    request: UpsertTemplateRequest,
    admin: UserInfo = Depends(require_admin),
):
    logger.info("PUT /purchase-notice-backward-templates/%s/%s — admin=%s, body_text_len=%d, entity=%s",
                company_id, period_type, admin.user_id, len(request.body_text), request.agreed_accepted_entity)
    result = await repo.upsert_backward_notice_template(
        period_type, request.body_text, request.agreed_accepted_entity, company_id
    )
    logger.debug("PUT /purchase-notice-backward-templates/%s/%s — upserted successfully", company_id, period_type)
    return result



@router.get("/purchase-confirmation-templates")
async def list_confirmation_templates(admin: UserInfo = Depends(require_admin)):
    logger.info("GET /purchase-confirmation-templates — admin=%s", admin.user_id)
    templates = await repo.get_all_confirmation_templates()
    return templates


@router.get("/purchase-confirmation-templates/company/{company_id}")
async def list_company_confirmation_templates(company_id: int, admin: UserInfo = Depends(require_admin)):
    logger.info("GET /purchase-confirmation-templates/company/%s — admin=%s", company_id, admin.user_id)
    templates = await repo.get_confirmation_templates_by_company(company_id)
    return templates


@router.get("/purchase-confirmation-templates/{company_id}/{period_type}")
async def get_confirmation_template(company_id: int, period_type: str, admin: UserInfo = Depends(require_admin)):
    logger.info("GET /purchase-confirmation-templates/%s/%s — admin=%s", company_id, period_type, admin.user_id)
    template = await repo.get_confirmation_template_by_period_type(period_type, company_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"No confirmation template for company {company_id}, period type: {period_type}")
    return template


@router.put("/purchase-confirmation-templates/{company_id}/{period_type}")
async def upsert_confirmation_template(
    company_id: int,
    period_type: str,
    request: UpsertTemplateRequest,
    admin: UserInfo = Depends(require_admin),
):
    logger.info("PUT /purchase-confirmation-templates/%s/%s — admin=%s, body_text_len=%d, entity=%s",
                company_id, period_type, admin.user_id, len(request.body_text), request.agreed_accepted_entity)
    result = await repo.upsert_confirmation_template(
        period_type, request.body_text, request.agreed_accepted_entity, company_id
    )
    return result

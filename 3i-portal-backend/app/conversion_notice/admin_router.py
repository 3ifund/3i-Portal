
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.conversion_notice.models import MapTemplateRequest
from app.conversion_notice import mongo_repository as repo
from app.onprem import client as onprem

logger = logging.getLogger("portal.admin.conversion_notice")
router = APIRouter()


@router.get("/conversion-notice/classes")
async def list_classes(admin: UserInfo = Depends(require_admin)):
    logger.info("GET /conversion-notice/classes by user=%s", admin.user_id)
    companies = await onprem.get_conversion_notice_classes()
    mappings = {m["instrument_id"]: m["template_id"] for m in await repo.list_mappings()}
    names = {t["template_id"]: t["name"] for t in await repo.list_templates()}
    for company in companies:
        for tranche in company.get("tranches", []):
            tid = mappings.get(tranche.get("instrumentId"))
            tranche["templateId"] = tid
            tranche["templateName"] = names.get(tid) if tid else None
    logger.info("  -> %s company(ies) with conversions", len(companies))
    return companies


@router.get("/conversion-notice/templates")
async def list_templates(admin: UserInfo = Depends(require_admin)):
    logger.info("GET /conversion-notice/templates by user=%s", admin.user_id)
    templates = await repo.list_templates()
    logger.info("  -> %s template(s)", len(templates))
    return templates


@router.get("/conversion-notice/templates/{template_id}")
async def get_template(template_id: str, admin: UserInfo = Depends(require_admin)):
    logger.info("GET /conversion-notice/templates/%s by user=%s", template_id, admin.user_id)
    tpl = await repo.get_template(template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    return tpl


@router.put("/conversion-notice/mappings")
async def map_template(request: MapTemplateRequest, admin: UserInfo = Depends(require_admin)):
    logger.info("PUT /conversion-notice/mappings instrument=%s template=%s by user=%s",
                request.instrument_id, request.template_id, admin.user_id)
    if await repo.get_template(request.template_id) is None:
        raise HTTPException(status_code=400, detail=f"Template '{request.template_id}' not found")
    await repo.upsert_mapping(request.instrument_id, request.template_id)
    return {"instrument_id": request.instrument_id, "template_id": request.template_id}


@router.delete("/conversion-notice/mappings/{instrument_id}")
async def unmap_template(instrument_id: int, admin: UserInfo = Depends(require_admin)):
    logger.info("DELETE /conversion-notice/mappings/%s by user=%s", instrument_id, admin.user_id)
    deleted = await repo.delete_mapping(instrument_id)
    return {"instrument_id": instrument_id, "deleted": deleted}

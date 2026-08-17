
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.conversion_notice.models import MapTemplateRequest
from app.conversion_notice import mongo_repository as repo
from app.onprem import client as onprem

logger = logging.getLogger("portal.admin.conversion_notice")


def build_router(kind: str, classes_fn=None) -> APIRouter:
    # classes_fn returns the companies+instruments to map (default: convertible-note tranches). Preferred passes a
    # source that returns companies + SERIES (the series is the instrument; no tranche level).
    classes_fn = classes_fn or onprem.get_conversion_notice_classes
    router = APIRouter()

    @router.get("/templates")
    async def list_templates(admin: UserInfo = Depends(require_admin)):
        logger.info("GET %s/templates by user=%s", kind, admin.user_id)
        templates = await repo.list_templates(kind)
        logger.info("  -> %s template(s) (%s)", len(templates), kind)
        return templates

    @router.get("/templates/{template_id}")
    async def get_template(template_id: str, admin: UserInfo = Depends(require_admin)):
        logger.info("GET %s/templates/%s by user=%s", kind, template_id, admin.user_id)
        tpl = await repo.get_template(template_id)
        if tpl is None or tpl.get("kind") != kind:
            raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
        return tpl

    @router.get("/classes")
    async def list_classes(admin: UserInfo = Depends(require_admin)):
        logger.info("GET %s/classes by user=%s", kind, admin.user_id)
        companies = await classes_fn()
        mappings = {m["instrument_id"]: m["template_id"] for m in await repo.list_mappings(kind)}
        names = {t["template_id"]: t["name"] for t in await repo.list_templates(kind)}
        for company in companies:
            for tranche in company.get("tranches", []):
                tid = mappings.get(tranche.get("instrumentId"))
                tranche["templateId"] = tid
                tranche["templateName"] = names.get(tid) if tid else None
        logger.info("  -> %s company(ies) with conversions (%s)", len(companies), kind)
        return companies

    @router.put("/mappings")
    async def map_template(request: MapTemplateRequest, admin: UserInfo = Depends(require_admin)):
        logger.info("PUT %s/mappings instrument=%s template=%s by user=%s",
                    kind, request.instrument_id, request.template_id, admin.user_id)
        tpl = await repo.get_template(request.template_id)
        if tpl is None or tpl.get("kind") != kind:
            raise HTTPException(status_code=400, detail=f"Template '{request.template_id}' not found for {kind}")
        await repo.upsert_mapping(request.instrument_id, request.template_id, kind)
        return {"instrument_id": request.instrument_id, "template_id": request.template_id}

    @router.delete("/mappings/{instrument_id}")
    async def unmap_template(instrument_id: int, admin: UserInfo = Depends(require_admin)):
        logger.info("DELETE %s/mappings/%s by user=%s", kind, instrument_id, admin.user_id)
        deleted = await repo.delete_mapping(instrument_id, kind)
        return {"instrument_id": instrument_id, "deleted": deleted}

    return router


notice_router = build_router(repo.KIND_NOTICE)
details_router = build_router(repo.KIND_DETAILS)
preferred_router = build_router(repo.KIND_PREFERRED, onprem.get_preferred_notice_classes)

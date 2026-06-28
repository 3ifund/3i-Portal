"""
3i Fund Portal — Admin Participation-ELOC Template Endpoints

Named, company-specific Purchase Notice / Purchase Confirmation templates plus
(company, pricing_period, document_type) -> template mappings, for the new
participation-ELOC workflow. All endpoints require admin role.

Isolated from the legacy purchase-notice-template endpoints. Extensive logging throughout.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.participation_templates.models import (
    DOCUMENT_TYPES,
    UpsertParticipationTemplateRequest,
    UpsertMappingRequest,
)
from app.participation_templates import mongo_repository as repo
from app.onprem import client as onprem

logger = logging.getLogger("portal.admin.participation_templates")
router = APIRouter()


def _validate_document_type(document_type: str) -> None:
    if document_type not in DOCUMENT_TYPES:
        logger.warning("Invalid document_type=%s (valid: %s)", document_type, list(DOCUMENT_TYPES))
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document_type '{document_type}'. Valid: {list(DOCUMENT_TYPES)}",
        )


# ---------------------------------------------------------------------------
# Field catalog (proxied from DealTermsServer)
# ---------------------------------------------------------------------------

@router.get("/participation-field-catalog/{document_type}")
async def get_field_catalog(document_type: str, admin: UserInfo = Depends(require_admin)):
    """Proxy the DealTermsServer field catalog for the editor's field dropdown."""
    logger.info("GET /participation-field-catalog/%s — admin=%s", document_type, admin.user_id)
    _validate_document_type(document_type)
    try:
        catalog = await onprem.get_template_field_catalog(document_type)
    except Exception as exc:
        logger.error("GET /participation-field-catalog/%s — DTS fetch FAILED: %s",
                     document_type, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")
    logger.info("GET /participation-field-catalog/%s — returned %d fields", document_type, len(catalog))
    return catalog


@router.post("/participation-pdf/preview")
async def preview_participation_pdf(payload: dict, admin: UserInfo = Depends(require_admin)):
    """Proxy the DealTermsServer PDF preview renderer; returns the rendered PDF bytes."""
    logger.info("POST /participation-pdf/preview — admin=%s, docType=%s, fields=%d",
                admin.user_id, payload.get("documentType"), len(payload.get("fields") or []))
    try:
        status_code, content, content_type = await onprem.render_participation_pdf_preview(payload)
    except Exception as exc:
        logger.error("POST /participation-pdf/preview — DTS render FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")
    if status_code != 200:
        detail = content.decode("utf-8", errors="replace") if content else "PDF render failed"
        logger.warning("POST /participation-pdf/preview — DTS status=%s: %s", status_code, detail[:300])
        raise HTTPException(status_code=status_code if status_code < 500 else 502, detail=detail)
    return Response(content=content, media_type=content_type or "application/pdf")


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

@router.get("/participation-templates")
async def list_templates(
    company_id: int | None = Query(None),
    document_type: str | None = Query(None),
    admin: UserInfo = Depends(require_admin),
):
    """List participation templates, optionally filtered by company and/or document type."""
    logger.info("GET /participation-templates — admin=%s, company_id=%s, document_type=%s",
                admin.user_id, company_id, document_type)
    if document_type is not None:
        _validate_document_type(document_type)
    templates = await repo.list_templates(company_id, document_type)
    logger.info("GET /participation-templates — returned %d", len(templates))
    return templates


# NOTE: declared BEFORE /{template_id} so the literal path wins the route match.
@router.get("/participation-templates/resolve")
async def resolve_template(
    company_id: int = Query(...),
    pricing_period_type: str = Query(...),
    document_type: str = Query(...),
    admin: UserInfo = Depends(require_admin),
):
    """Resolve (company, pricing period, document type) -> the mapped template."""
    logger.info("GET /participation-templates/resolve — admin=%s, company_id=%s, pricing_period_type=%s, document_type=%s",
                admin.user_id, company_id, pricing_period_type, document_type)
    _validate_document_type(document_type)
    template = await repo.resolve(company_id, pricing_period_type, document_type)
    if template is None:
        logger.warning("GET /participation-templates/resolve — nothing resolved")
        raise HTTPException(
            status_code=404,
            detail="No template mapped for that company / pricing period / document type",
        )
    return template


@router.get("/participation-templates/{template_id}")
async def get_template(template_id: str, admin: UserInfo = Depends(require_admin)):
    logger.info("GET /participation-templates/%s — admin=%s", template_id, admin.user_id)
    template = await repo.get_template(template_id)
    if template is None:
        logger.warning("GET /participation-templates/%s — not found", template_id)
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")
    return template


@router.post("/participation-templates")
async def create_template(
    request: UpsertParticipationTemplateRequest,
    admin: UserInfo = Depends(require_admin),
):
    logger.info("POST /participation-templates — admin=%s, name=%s, company_id=%s, document_type=%s, fields=%d",
                admin.user_id, request.name, request.company_id, request.document_type, len(request.fields))
    _validate_document_type(request.document_type)
    if await repo.name_exists(request.company_id, request.document_type, request.name):
        logger.warning("POST /participation-templates — duplicate name=%s for company_id=%s, document_type=%s",
                       request.name, request.company_id, request.document_type)
        raise HTTPException(
            status_code=409,
            detail=f"A {request.document_type} template named '{request.name}' already exists for this company",
        )
    fields = [f.model_dump() for f in request.fields]
    template = await repo.create_template(
        request.name, request.company_id, request.document_type,
        request.body_text, request.agreed_accepted_entity, fields,
        allocation_type=request.allocation_type)
    logger.info("POST /participation-templates — created template_id=%s", template["template_id"])
    return template


@router.put("/participation-templates/{template_id}")
async def update_template(
    template_id: str,
    request: UpsertParticipationTemplateRequest,
    admin: UserInfo = Depends(require_admin),
):
    logger.info("PUT /participation-templates/%s — admin=%s, name=%s, company_id=%s, document_type=%s, fields=%d",
                template_id, admin.user_id, request.name, request.company_id, request.document_type, len(request.fields))
    _validate_document_type(request.document_type)
    if await repo.name_exists(request.company_id, request.document_type, request.name,
                              exclude_template_id=template_id):
        logger.warning("PUT /participation-templates/%s — duplicate name=%s", template_id, request.name)
        raise HTTPException(
            status_code=409,
            detail=f"A {request.document_type} template named '{request.name}' already exists for this company",
        )
    fields = [f.model_dump() for f in request.fields]
    template = await repo.update_template(
        template_id, request.name, request.company_id, request.document_type,
        request.body_text, request.agreed_accepted_entity, fields,
        allocation_type=request.allocation_type)
    if template is None:
        logger.warning("PUT /participation-templates/%s — not found", template_id)
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")
    logger.info("PUT /participation-templates/%s — updated", template_id)
    return template


@router.delete("/participation-templates/{template_id}")
async def delete_template(template_id: str, admin: UserInfo = Depends(require_admin)):
    logger.info("DELETE /participation-templates/%s — admin=%s", template_id, admin.user_id)
    referencing = await repo.list_mappings_for_template(template_id)
    if referencing:
        logger.warning("DELETE /participation-templates/%s — blocked, %d mapping(s) reference it",
                       template_id, len(referencing))
        raise HTTPException(
            status_code=409,
            detail=f"Template is mapped to {len(referencing)} pricing period(s); remove those mappings first",
        )
    deleted = await repo.delete_template(template_id)
    if not deleted:
        logger.warning("DELETE /participation-templates/%s — not found", template_id)
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")
    logger.info("DELETE /participation-templates/%s — deleted", template_id)
    return {"deleted": True, "template_id": template_id}


# ---------------------------------------------------------------------------
# Mappings
# ---------------------------------------------------------------------------

@router.get("/participation-template-mappings")
async def list_mappings(
    company_id: int | None = Query(None),
    document_type: str | None = Query(None),
    admin: UserInfo = Depends(require_admin),
):
    logger.info("GET /participation-template-mappings — admin=%s, company_id=%s, document_type=%s",
                admin.user_id, company_id, document_type)
    if document_type is not None:
        _validate_document_type(document_type)
    mappings = await repo.list_mappings(company_id, document_type)
    logger.info("GET /participation-template-mappings — returned %d", len(mappings))
    return mappings


@router.put("/participation-template-mappings")
async def upsert_mapping(request: UpsertMappingRequest, admin: UserInfo = Depends(require_admin)):
    logger.info("PUT /participation-template-mappings — admin=%s, company_id=%s, pricing_period_type=%s, document_type=%s, template_id=%s",
                admin.user_id, request.company_id, request.pricing_period_type, request.document_type, request.template_id)
    _validate_document_type(request.document_type)

    template = await repo.get_template(request.template_id)
    if template is None:
        logger.warning("PUT /participation-template-mappings — template_id=%s not found", request.template_id)
        raise HTTPException(status_code=400, detail=f"Template not found: {request.template_id}")
    if template["company_id"] != request.company_id:
        logger.warning("PUT /participation-template-mappings — template company_id=%s != mapping company_id=%s",
                       template["company_id"], request.company_id)
        raise HTTPException(status_code=400, detail="Template belongs to a different company")
    if template["document_type"] != request.document_type:
        logger.warning("PUT /participation-template-mappings — template document_type=%s != mapping document_type=%s",
                       template["document_type"], request.document_type)
        raise HTTPException(status_code=400, detail="Template document_type does not match mapping document_type")

    mapping = await repo.upsert_mapping(
        request.company_id, request.pricing_period_type, request.document_type, request.template_id)
    logger.info("PUT /participation-template-mappings — upserted")
    return mapping


@router.delete("/participation-template-mappings")
async def delete_mapping(
    company_id: int = Query(...),
    pricing_period_type: str = Query(...),
    document_type: str = Query(...),
    admin: UserInfo = Depends(require_admin),
):
    logger.info("DELETE /participation-template-mappings — admin=%s, company_id=%s, pricing_period_type=%s, document_type=%s",
                admin.user_id, company_id, pricing_period_type, document_type)
    _validate_document_type(document_type)
    deleted = await repo.delete_mapping(company_id, pricing_period_type, document_type)
    if not deleted:
        logger.warning("DELETE /participation-template-mappings — not found")
        raise HTTPException(status_code=404, detail="Mapping not found")
    return {"deleted": True}

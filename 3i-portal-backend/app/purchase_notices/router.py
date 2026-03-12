"""
3i Fund Portal — Purchase Notice Endpoints (User)
Signatory management + purchase notice prefill.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from fastapi import status

from app.auth.dependencies import get_current_user
from app.auth.models import UserInfo
from app.purchase_notices.models import (
    CreateSignatoryRequest,
    PortalPurchaseNoticeRequest,
    UpdateSignatoryRequest,
)
from app.purchase_notices import mongo_repository as repo
from app.onprem import client as onprem

logger = logging.getLogger("portal.purchase_notices")
router = APIRouter()


# ---- Signatories ----

@router.get("/signatories")
async def list_signatories(user: UserInfo = Depends(get_current_user)):
    """List the current user's signatories."""
    logger.info("GET /signatories — user=%s", user.user_id)
    signatories = await repo.get_signatories(user.user_id)
    logger.debug("GET /signatories — user=%s — returned %d signatories", user.user_id, len(signatories))
    return signatories


@router.post("/signatories", status_code=201)
async def add_signatory(
    request: CreateSignatoryRequest,
    user: UserInfo = Depends(get_current_user),
):
    """Add a signatory to the current user's list."""
    logger.info("POST /signatories — user=%s, name=%s, title=%s, email=%s",
                user.user_id, request.name, request.title, request.email)
    signatory = await repo.add_signatory(
        user.user_id, request.name, request.title, request.address, request.email,
        request.signature_image
    )
    logger.debug("POST /signatories — created signatory id=%s for user=%s", signatory.get("_id"), user.user_id)
    return signatory


@router.put("/signatories/{signatory_id}")
async def update_signatory(
    signatory_id: str,
    request: UpdateSignatoryRequest,
    user: UserInfo = Depends(get_current_user),
):
    """Update a signatory."""
    updates = request.model_dump(exclude_none=True)
    logger.info("PUT /signatories/%s — user=%s, updates=%s", signatory_id, user.user_id, updates)
    if not updates:
        logger.warning("PUT /signatories/%s — no fields to update", signatory_id)
        raise HTTPException(status_code=400, detail="No fields to update")
    ok = await repo.update_signatory(user.user_id, signatory_id, updates)
    if not ok:
        logger.warning("PUT /signatories/%s — not found for user=%s", signatory_id, user.user_id)
        raise HTTPException(status_code=404, detail="Signatory not found")
    logger.debug("PUT /signatories/%s — updated successfully", signatory_id)
    return {"status": "updated"}


@router.delete("/signatories/{signatory_id}")
async def delete_signatory(
    signatory_id: str,
    user: UserInfo = Depends(get_current_user),
):
    """Delete a signatory."""
    logger.info("DELETE /signatories/%s — user=%s", signatory_id, user.user_id)
    ok = await repo.delete_signatory(user.user_id, signatory_id)
    if not ok:
        logger.warning("DELETE /signatories/%s — not found for user=%s", signatory_id, user.user_id)
        raise HTTPException(status_code=404, detail="Signatory not found")
    logger.debug("DELETE /signatories/%s — deleted successfully", signatory_id)
    return {"status": "deleted"}


# ---- Purchase Notice Prefill ----

@router.get("/prefill/{symbol}/{pricing_period_id}")
async def get_prefill(
    symbol: str,
    pricing_period_id: int,
    shares: int = Query(..., gt=0),
    user: UserInfo = Depends(get_current_user),
):
    """
    Get all data needed to render a purchase notice.
    Merges DTS calculated fields + MongoDB template + user signatories.
    """
    logger.info("GET /prefill/%s/%d?shares=%d — user=%s, company=%s",
                symbol, pricing_period_id, shares, user.user_id, user.company_name)

    # 1. Get calculated fields from DTS
    logger.debug("Calling DTS get_purchase_notice_fields(%s, %d)", symbol, pricing_period_id)
    fields = await onprem.get_purchase_notice_fields(symbol, pricing_period_id)
    if not fields:
        logger.warning("DTS returned no data for %s / period %d", symbol, pricing_period_id)
        raise HTTPException(
            status_code=404,
            detail=f"No purchase notice data for {symbol} / period {pricing_period_id}",
        )
    logger.debug("DTS fields received: periodType=%s, exerciseDate=%s, withinWindow=%s, signer=%s",
                 fields.get("periodType"), fields.get("exerciseDate"),
                 fields.get("isWithinAcceptanceWindow"), fields.get("signerName"))

    # 2. Get template from MongoDB (company-specific, with legacy fallback)
    period_type = fields.get("periodType", "")
    company_id = int(user.company_id) if user.company_id else None
    logger.debug("Looking up template for company_id=%s, period_type=%s", company_id, period_type)
    template = await repo.get_template_by_period_type(period_type, company_id)
    body_text = template.get("body_text", "") if template else ""
    agreed_entity = template.get("agreed_accepted_entity", "") if template else ""
    logger.debug("Template found=%s, body_text_len=%d, entity=%s",
                 template is not None, len(body_text), agreed_entity)

    # 3. Get user's signatories
    logger.debug("Loading signatories for user=%s", user.user_id)
    signatories = await repo.get_signatories(user.user_id)
    logger.debug("Found %d signatories for user=%s", len(signatories), user.user_id)

    # 4. Return merged response
    logger.info("Prefill response ready: %s %s exercise=%s valuation=%s-%s settlement=%s shares=%d signatories=%d",
                symbol, period_type, fields.get("exerciseDate"), fields.get("valuationPeriodStart"),
                fields.get("valuationPeriodEnd"), fields.get("settlementDate"), shares, len(signatories))
    return {
        **fields,
        "body_text": body_text,
        "agreed_accepted_entity": agreed_entity,
        "shares": shares,
        "signatories": signatories,
    }


# ---- Portal-Initiated Purchase Notice Submission ----

@router.post("/submit")
async def submit_portal_purchase_notice(
    request: PortalPurchaseNoticeRequest,
    user: UserInfo = Depends(get_current_user),
):
    """
    Submit a portal-initiated purchase notice to DTS.
    DTS generates the PDF, creates eloc_id, writes to three_i_fund_portal MongoDB,
    and returns the eloc_id.
    """
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no company assigned",
        )

    logger.info(
        "POST /submit — user=%s symbol=%s period=%d shares=%d signatory=%s company_id=%s",
        user.user_id, request.symbol, request.pricing_period_id,
        request.shares, request.signatory_name, user.company_id,
    )

    payload = {
        **request.model_dump(),
        "company_id": int(user.company_id),
        "company_name": user.company_name or "",
        "submitted_by": user.user_id,
    }

    logger.debug(
        "POST /submit payload keys: %s",
        list(payload.keys()),
    )
    logger.debug(
        "POST /submit payload (core): symbol=%s, pricing_period_id=%s, shares=%s, "
        "company_id=%s, company_name=%s, signatory_name=%s, period_type=%s, "
        "exercise_date=%s, settlement_date=%s",
        payload.get("symbol"), payload.get("pricing_period_id"), payload.get("shares"),
        payload.get("company_id"), payload.get("company_name"), payload.get("signatory_name"),
        payload.get("period_type"), payload.get("exercise_date"), payload.get("settlement_date"),
    )

    try:
        result = await onprem.submit_portal_purchase_notice(payload)
    except Exception as exc:
        logger.error("Portal purchase notice submission failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unable to submit purchase notice: {exc}",
        )

    logger.info("Portal purchase notice submitted: %s", result)
    return result


@router.get("/documents/{eloc_id}/{step}")
async def get_portal_document(
    eloc_id: str,
    step: str,
    user: UserInfo = Depends(get_current_user),
):
    """
    Fetch document for a portal-initiated ELOC workflow step.
    Returns PDF data from three_i_fund_portal.eloc_data via DTS.
    """
    logger.info("GET /documents/%s/%s — user=%s", eloc_id, step, user.user_id)

    doc = await onprem.get_portal_eloc_document(eloc_id, step)
    if not doc:
        logger.warning("Document not found for eloc=%s step=%s", eloc_id, step)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found for this step",
        )

    logger.info("Document returned for eloc=%s step=%s", eloc_id, step)
    return doc

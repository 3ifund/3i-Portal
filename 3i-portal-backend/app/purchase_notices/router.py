"""
3i Fund Portal — Purchase Notice Endpoints (User)
Signatory management + purchase notice prefill.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import get_current_user
from app.auth.models import UserInfo
from app.purchase_notices.models import CreateSignatoryRequest, UpdateSignatoryRequest
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

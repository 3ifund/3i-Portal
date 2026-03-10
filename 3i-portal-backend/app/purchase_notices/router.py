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
    return await repo.get_signatories(user.user_id)


@router.post("/signatories", status_code=201)
async def add_signatory(
    request: CreateSignatoryRequest,
    user: UserInfo = Depends(get_current_user),
):
    """Add a signatory to the current user's list."""
    signatory = await repo.add_signatory(
        user.user_id, request.name, request.title, request.address, request.email
    )
    return signatory


@router.put("/signatories/{signatory_id}")
async def update_signatory(
    signatory_id: str,
    request: UpdateSignatoryRequest,
    user: UserInfo = Depends(get_current_user),
):
    """Update a signatory."""
    updates = request.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    ok = await repo.update_signatory(user.user_id, signatory_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Signatory not found")
    return {"status": "updated"}


@router.delete("/signatories/{signatory_id}")
async def delete_signatory(
    signatory_id: str,
    user: UserInfo = Depends(get_current_user),
):
    """Delete a signatory."""
    ok = await repo.delete_signatory(user.user_id, signatory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Signatory not found")
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
    logger.info("Prefill request: user=%s symbol=%s period=%d shares=%d",
                user.user_id, symbol, pricing_period_id, shares)

    # 1. Get calculated fields from DTS
    fields = await onprem.get_purchase_notice_fields(symbol, pricing_period_id)
    if not fields:
        raise HTTPException(
            status_code=404,
            detail=f"No purchase notice data for {symbol} / period {pricing_period_id}",
        )

    # 2. Get template from MongoDB
    period_type = fields.get("periodType", "")
    template = await repo.get_template_by_period_type(period_type)
    body_text = template.get("body_text", "") if template else ""
    agreed_entity = template.get("agreed_accepted_entity", "") if template else ""

    # 3. Get user's signatories
    signatories = await repo.get_signatories(user.user_id)

    # 4. Return merged response
    return {
        **fields,
        "body_text": body_text,
        "agreed_accepted_entity": agreed_entity,
        "shares": shares,
        "signatories": signatories,
    }

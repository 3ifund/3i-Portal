"""
3i Fund Portal — ELOC Router
Endpoints for ELOC listing, detail, workflow, documents, and purchase notices.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.dependencies import get_current_user
from app.auth.models import UserInfo
from app.elocs import service
from app.elocs.models import (
    ElocDetail,
    ElocSummary,
    PricingWorkflowState,
    PurchaseNoticeRequest,
    PurchaseNoticeResponse,
    WorkflowResponse,
)

logger = logging.getLogger("portal.elocs")
router = APIRouter()


@router.get("", response_model=list[ElocSummary])
async def list_elocs(
    status_filter: str | None = Query(None, alias="status"),
    user: UserInfo = Depends(get_current_user),
):
    """List ELOCs for the authenticated user's company."""
    logger.info("GET /elocs user=%s company_id=%s status=%s", user.user_id, user.company_id, status_filter)
    company_id = int(user.company_id) if user.company_id else None
    if company_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no company_id assigned",
        )
    elocs = await service.get_company_elocs(company_id, user.company_symbol, status_filter)
    logger.info("  → returned %d ELOCs", len(elocs))
    return elocs


@router.get("/shares-available")
async def get_shares_available(
    user: UserInfo = Depends(get_current_user),
):
    """Get available shares for all pricing periods from DealTermsServer."""
    logger.info("GET /elocs/shares-available user=%s symbol=%s", user.user_id, user.company_symbol)
    if not user.company_symbol:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no company_symbol assigned",
        )
    try:
        result = await service.get_shares_available(user.company_symbol)
        logger.info("  → shares-available returned OK (keys: %s)", list(result.keys()) if isinstance(result, dict) else type(result))
        return result
    except Exception as exc:
        logger.error("  → shares-available FAILED: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unable to fetch shares available: {exc}",
        )


@router.get("/action-items")
async def get_action_items(
    user: UserInfo = Depends(get_current_user),
):
    """Get pending action items for the authenticated user's company."""
    logger.info("GET /elocs/action-items user=%s company_id=%s", user.user_id, user.company_id)
    company_id = int(user.company_id) if user.company_id else None
    if company_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no company_id assigned",
        )
    items = await service.get_action_items(company_id)
    logger.info("  → returned %d action items", len(items))
    return items


@router.get("/pricing-workflows", response_model=list[PricingWorkflowState])
async def get_pricing_workflows(
    user: UserInfo = Depends(get_current_user),
):
    """Get workflow states for ELOCs currently pricing (include=true)."""
    logger.info("GET /elocs/pricing-workflows user=%s company_id=%s", user.user_id, user.company_id)
    company_id = int(user.company_id) if user.company_id else None
    if company_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no company_id assigned",
        )
    workflows = await service.get_pricing_workflows(company_id)
    logger.info("  → returned %d pricing workflows", len(workflows))
    return workflows


@router.post("/{eloc_id}/workflow/remove")
async def remove_pricing_workflow(
    eloc_id: str,
    user: UserInfo = Depends(get_current_user),
):
    """Remove an ELOC from 'Currently Pricing' by setting include=false."""
    logger.info("POST /elocs/%s/workflow/remove user=%s", eloc_id, user.user_id)
    company_id = int(user.company_id) if user.company_id else None
    if company_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no company_id assigned",
        )
    removed = await service.remove_pricing_workflow(eloc_id, company_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove: workflow must be rejected or fully completed",
        )
    logger.info("  → ELOC %s removed from pricing workflows", eloc_id)
    return {"status": "removed"}


@router.get("/{eloc_id}", response_model=ElocDetail)
async def get_eloc(
    eloc_id: int,
    user: UserInfo = Depends(get_current_user),
):
    """Get ELOC detail: pricing periods, shares, deal terms."""
    logger.info("GET /elocs/%s user=%s company_id=%s", eloc_id, user.user_id, user.company_id)
    company_id = int(user.company_id) if user.company_id else None
    if company_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no company_id assigned",
        )
    detail = await service.get_eloc_detail(eloc_id, company_id, user.company_symbol or "")
    if not detail:
        logger.warning("  → ELOC %s not found", eloc_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ELOC deal not found",
        )
    logger.info("  → ELOC %s returned OK", eloc_id)
    return detail


@router.get("/{eloc_id}/workflow", response_model=WorkflowResponse)
async def get_workflow(
    eloc_id: str,
    user: UserInfo = Depends(get_current_user),
):
    """Get workflow state and event data from DealTermsServer."""
    logger.info("GET /elocs/%s/workflow user=%s", eloc_id, user.user_id)
    workflow = await service.get_eloc_workflow(eloc_id)
    logger.info("  → workflow steps: %s", list(workflow.get("steps", {}).keys()))
    return workflow


@router.get("/{eloc_id}/documents/{step}")
async def get_document(
    eloc_id: str,
    step: str,
    user: UserInfo = Depends(get_current_user),
):
    """Get the document for a specific workflow step."""
    logger.info("GET /elocs/%s/documents/%s user=%s", eloc_id, step, user.user_id)
    doc = await service.get_eloc_document(eloc_id, step)
    if not doc:
        logger.warning("  → document not found for eloc=%s step=%s", eloc_id, step)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found for this step",
        )
    logger.info("  → document returned OK")
    return doc


@router.post("/{eloc_id}/purchase-notice", response_model=PurchaseNoticeResponse)
async def submit_purchase_notice(
    eloc_id: str,
    request: PurchaseNoticeRequest,
    user: UserInfo = Depends(get_current_user),
):
    """Submit a purchase notice to the on-prem server."""
    logger.info(
        "POST /elocs/%s/purchase-notice user=%s period=%s shares=%d",
        eloc_id, user.user_id, request.pricing_period, request.shares,
    )
    if request.shares < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shares must be at least 1",
        )

    try:
        result = await service.submit_purchase_notice(
            eloc_id, user.company_id, request.pricing_period, request.shares
        )
    except Exception as exc:
        logger.error("  → purchase notice FAILED: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unable to submit purchase notice: {exc}",
        )

    logger.info("  → purchase notice result: %s", result)
    return PurchaseNoticeResponse(
        status=result.get("status", "acknowledged"),
        message=result.get("message", "Purchase notice submitted successfully"),
    )

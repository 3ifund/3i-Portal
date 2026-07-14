
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth.dependencies import get_current_user
from app.auth.models import UserInfo
from app.elocs import service
from app.elocs.models import (
    ElocDetail,
    ElocSummary,
    PricingWorkflowState,
    WorkflowResponse,
)

from app.onprem import client as onprem

logger = logging.getLogger("portal.elocs")
router = APIRouter()


async def _verify_eloc_ownership(eloc_id: str, company_id: int) -> None:
    import time
    t_start = time.monotonic()
    tag = f"verify-ownership:{eloc_id}"
    logger.info(
        "[%s] START — user_company_id=%s (trying Portal state first, DTS state on fallback)",
        tag, company_id,
    )

    state = None
    source = None

    t_portal_start = time.monotonic()
    try:
        state = await onprem.get_portal_eloc_state_by_id(eloc_id)
        portal_ms = (time.monotonic() - t_portal_start) * 1000
        if state:
            source = "portal"
            logger.info(
                "[%s] Portal state lookup → FOUND in %.1fms (companyId=%s, source=portal_3i.eloc_state)",
                tag, portal_ms, state.get("companyId"),
            )
        else:
            logger.info(
                "[%s] Portal state lookup → not-found in %.1fms (404) — will try DTS state next",
                tag, portal_ms,
            )
    except Exception as exc:
        portal_ms = (time.monotonic() - t_portal_start) * 1000
        logger.warning(
            "[%s] Portal state lookup FAILED in %.1fms (non-fatal, trying DTS state next): %s: %s",
            tag, portal_ms, type(exc).__name__, exc,
        )

    if not state:
        t_dts_start = time.monotonic()
        try:
            state = await onprem.get_eloc_state_by_id(eloc_id)
            dts_ms = (time.monotonic() - t_dts_start) * 1000
            if state:
                source = "dts"
                logger.info(
                    "[%s] DTS state lookup → FOUND in %.1fms (companyId=%s, source=DTS eloc_state)",
                    tag, dts_ms, state.get("companyId"),
                )
            else:
                logger.warning(
                    "[%s] DTS state lookup → not-found in %.1fms (404) — both lookups failed",
                    tag, dts_ms,
                )
        except Exception as exc:
            dts_ms = (time.monotonic() - t_dts_start) * 1000
            logger.error(
                "[%s] DTS state lookup FAILED in %.1fms: %s: %s",
                tag, dts_ms, type(exc).__name__, exc,
            )

    if not state:
        total_ms = (time.monotonic() - t_start) * 1000
        logger.warning(
            "[%s] Ownership check → 404: ELOC not found in Portal state OR DTS state (total %.1fms)",
            tag, total_ms,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ELOC not found",
        )

    eloc_company_id = state.get("companyId")
    if eloc_company_id != company_id:
        total_ms = (time.monotonic() - t_start) * 1000
        logger.warning(
            "[%s] Ownership check → 403: user company_id=%s does NOT match ELOC company_id=%s (source=%s, total %.1fms)",
            tag, company_id, eloc_company_id, source, total_ms,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: ELOC belongs to a different company",
        )

    total_ms = (time.monotonic() - t_start) * 1000
    logger.info(
        "[%s] Ownership check → OK (source=%s, eloc_company_id=%s == user_company_id=%s, total %.1fms)",
        tag, source, eloc_company_id, company_id, total_ms,
    )


@router.get("", response_model=list[ElocSummary])
async def list_elocs(
    status_filter: str | None = Query(None, alias="status"),
    user: UserInfo = Depends(get_current_user),
):
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
    logger.info("POST /elocs/%s/workflow/remove (hide) user=%s", eloc_id, user.user_id)
    company_id = int(user.company_id) if user.company_id else None
    if company_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no company_id assigned",
        )
    await _verify_eloc_ownership(eloc_id, company_id)
    hidden = await service.remove_pricing_workflow(eloc_id, company_id)
    if not hidden:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to hide ELOC from client view",
        )
    logger.info("  → ELOC %s hidden from client Portal UI", eloc_id)
    return {"status": "hidden"}


@router.get("/{eloc_id}", response_model=ElocDetail)
async def get_eloc(
    eloc_id: str,
    user: UserInfo = Depends(get_current_user),
):
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
    logger.info("GET /elocs/%s/workflow user=%s", eloc_id, user.user_id)
    company_id = int(user.company_id) if user.company_id else None
    if company_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no company_id assigned",
        )
    await _verify_eloc_ownership(eloc_id, company_id)
    workflow = await service.get_eloc_workflow(eloc_id)
    logger.info("  → workflow steps: %s", list(workflow.get("steps", {}).keys()))
    return workflow


@router.get("/{eloc_id}/documents/{step}")
async def get_document(
    eloc_id: str,
    step: str,
    user: UserInfo = Depends(get_current_user),
):
    logger.info("GET /elocs/%s/documents/%s user=%s", eloc_id, step, user.user_id)
    company_id = int(user.company_id) if user.company_id else None
    if company_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no company_id assigned",
        )
    await _verify_eloc_ownership(eloc_id, company_id)
    doc = await service.get_eloc_document(eloc_id, step)
    if not doc:
        logger.warning("  → document not found for eloc=%s step=%s", eloc_id, step)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found for this step",
        )
    logger.info("  → document returned OK")
    return doc



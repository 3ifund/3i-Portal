
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.internal_elocs.models import derive_workflow_steps
from app.onprem import client as onprem

logger = logging.getLogger("portal.internal_elocs")
client_logger = logging.getLogger("portal.prm_client")
router = APIRouter()




class ClientLogEntry(BaseModel):
    """One log line shipped from the PRM web app (eloc.js clog())."""
    level: str = "info"
    event: str = ""
    message: str = ""
    eloc_id: str | None = None
    data: dict | None = None
    ts: str | None = None


@router.post("/clientlog")
async def client_log(entry: ClientLogEntry, admin: UserInfo = Depends(require_admin)):
    level = (entry.level or "info").lower()
    log_fn = {
        "debug": client_logger.debug,
        "info": client_logger.info,
        "warn": client_logger.warning,
        "warning": client_logger.warning,
        "error": client_logger.error,
    }.get(level, client_logger.info)

    try:
        data_str = json.dumps(entry.data, default=str) if entry.data else ""
    except Exception:
        data_str = repr(entry.data)

    log_fn(
        "PRM-CLIENT user=%s ts=%s event=%s eloc=%s msg=%s data=%s",
        admin.user_id, entry.ts or "", entry.event, entry.eloc_id or "",
        entry.message or "", data_str,
    )
    return {"ok": True}




@router.get("/elocs/states/included")
async def list_included_states(admin: UserInfo = Depends(require_admin)):
    t_start = time.monotonic()
    logger.info("GET /internal/elocs/states/included by user=%s — START", admin.user_id)

    try:
        raw = await onprem.get_portal_eloc_states_included()
    except Exception as exc:
        logger.error("GET /internal/elocs/states/included — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")

    logger.info("GET /internal/elocs/states/included — DTS returned %d states", len(raw))

    items: list[dict] = []
    skipped_hidden = 0
    for state in raw:
        if state.get("workflowVisible") is False:
            skipped_hidden += 1
            continue

        eloc_id = str(state.get("elocId", ""))
        company_id = int(state.get("companyId", 0) or 0)
        workflow_step = state.get("workflowStep", "") or ""
        status = state.get("status", "Pending") or "Pending"
        pricing_direction = state.get("pricingDirection", "Forward") or "Forward"
        workflow_complete = bool(state.get("workflowComplete", False))
        modified_at = state.get("modifiedAt")
        company_symbol = state.get("companySymbol") or state.get("symbol")

        steps = derive_workflow_steps(workflow_step, status, pricing_direction)

        items.append({
            "eloc_id": eloc_id,
            "company_id": company_id,
            "company_symbol": company_symbol,
            "workflow_step": workflow_step,
            "status": status,
            "pricing_direction": pricing_direction,
            "workflow_complete": workflow_complete,
            "modified_at": str(modified_at) if modified_at else None,
            "steps": steps,
        })

    t_total = (time.monotonic() - t_start) * 1000
    logger.info(
        "GET /internal/elocs/states/included — DONE in %.1fms (returned=%d, skipped_hidden=%d)",
        t_total, len(items), skipped_hidden,
    )
    return items




@router.post("/elocs/{eloc_id}/exclude")
async def exclude_eloc(eloc_id: str, admin: UserInfo = Depends(require_admin)):
    t_start = time.monotonic()
    logger.info("POST /internal/elocs/%s/exclude by user=%s — START", eloc_id, admin.user_id)

    try:
        ok = await onprem.exclude_portal_eloc(eloc_id)
    except Exception as exc:
        logger.error(
            "POST /internal/elocs/%s/exclude — DTS call FAILED: %s",
            eloc_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")

    t_total = (time.monotonic() - t_start) * 1000
    if not ok:
        logger.warning(
            "POST /internal/elocs/%s/exclude — DTS reported failure (%.1fms)",
            eloc_id, t_total,
        )
        raise HTTPException(status_code=502, detail="DTS reported exclude failure")

    logger.info(
        "POST /internal/elocs/%s/exclude — DONE in %.1fms (user=%s)",
        eloc_id, t_total, admin.user_id,
    )
    return {"status": "excluded", "eloc_id": eloc_id}




@router.post("/elocs/{eloc_id}/send-nudge")
async def send_eloc_nudge(eloc_id: str, admin: UserInfo = Depends(require_admin)):
    t_start = time.monotonic()
    logger.info("POST /internal/elocs/%s/send-nudge by user=%s — START", eloc_id, admin.user_id)

    try:
        body = await onprem.send_portal_eloc_nudge(eloc_id)
    except Exception as exc:
        logger.error(
            "POST /internal/elocs/%s/send-nudge — DTS call FAILED: %s",
            eloc_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")

    t_total = (time.monotonic() - t_start) * 1000
    logger.info(
        "POST /internal/elocs/%s/send-nudge — DONE in %.1fms (user=%s, symbol=%s, company=%s)",
        eloc_id, t_total, admin.user_id, body.get("symbol"), body.get("companyName"),
    )
    return body


@router.delete("/elocs/{eloc_id}")
async def delete_eloc(eloc_id: str, admin: UserInfo = Depends(require_admin)):
    t_start = time.monotonic()
    logger.info("DELETE /internal/elocs/%s by user=%s — START", eloc_id, admin.user_id)

    try:
        body = await onprem.delete_portal_eloc(eloc_id)
    except Exception as exc:
        logger.error(
            "DELETE /internal/elocs/%s — DTS call FAILED: %s",
            eloc_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")

    t_total = (time.monotonic() - t_start) * 1000
    if body is None:
        logger.warning(
            "DELETE /internal/elocs/%s — DTS returned non-success or unparsable body (%.1fms)",
            eloc_id, t_total,
        )
        raise HTTPException(status_code=502, detail="DTS delete failed")

    logger.info(
        "DELETE /internal/elocs/%s — DONE in %.1fms (user=%s, deletedCount=%s, "
        "sharesOutcome=%s, commitmentOutcome=%s)",
        eloc_id, t_total, admin.user_id,
        body.get("deletedCount"),
        body.get("sharesOutcome"),
        body.get("commitmentOutcome"),
    )
    return body

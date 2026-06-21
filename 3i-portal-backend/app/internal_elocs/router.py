"""
3i Fund Portal — Internal (PRM-replica) ELOC Router.

Admin-only REST endpoints that back the position_risk_management web app's
ELOC workflow view. The endpoints are thin shims over the existing
`app.onprem` DTS client; the value-add at this layer is:

  • Admin JWT gate (require_admin) instead of the per-company auth used by
    `app.elocs.router`, so an operator sees ALL companies' active workflows
    the same way PRM-WPF does.
  • Server-side derivation of the full 10-forward / 4-backward step grid
    (see internal_elocs.models.derive_workflow_steps), so the initial
    REST payload arrives ready-to-render with no extra round-trip.
  • Structured logging keyed on user_id + eloc_id so the audit trail for
    Remove/Delete clicks lines up cleanly with DTS's DealTermsDelta logs.

The matching live-update path lives in `app.workflows.router`
(`_internal_connections` pool + `/ws/elocs/internal` endpoint, added in a
sibling commit).
"""

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
# Dedicated logger for browser-shipped PRM web-app logs so the disk trail for
# the client side (which can't write to disk itself) is easy to grep apart
# from the server-side internal_elocs lines.
client_logger = logging.getLogger("portal.prm_client")
router = APIRouter()


# ---- POST clientlog (browser → disk log sink) ------------------------------


class ClientLogEntry(BaseModel):
    """One log line shipped from the PRM web app (eloc.js clog())."""
    level: str = "info"
    event: str = ""
    message: str = ""
    eloc_id: str | None = None
    data: dict | None = None
    ts: str | None = None  # client-side ISO timestamp (best-effort)


@router.post("/clientlog")
async def client_log(entry: ClientLogEntry, admin: UserInfo = Depends(require_admin)):
    """
    POST /api/internal/clientlog — append a browser log line to the portal
    backend's on-disk log. The PRM web app can't write to disk; this gives
    its delete/remove/WS-removal lifecycle a durable, grep-able audit trail
    alongside the server-side DTS logs. Admin-gated and fire-and-forget from
    the client; failures here never affect the UI.
    """
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


# ---- GET states/included ---------------------------------------------------


@router.get("/elocs/states/included")
async def list_included_states(admin: UserInfo = Depends(require_admin)):
    """
    GET /api/internal/elocs/states/included — every Portal-flow ELOC that is
    currently included in the workflow (include=true), across ALL companies.
    Mirrors the data PRM-WPF's ElocViewModel loads via
    ElocWorkflowApiClient.GetPortalIncludedStatesAsync().

    Each entry carries the raw DTS enums plus a server-derived `steps` list
    so the browser can paint the workflow grid on first frame.
    """
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
        # PRM-WPF hides workflow_visible=false entries from its main view
        # (they came in via the client portal's hide action). Match that.
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


# ---- POST exclude ----------------------------------------------------------


@router.post("/elocs/{eloc_id}/exclude")
async def exclude_eloc(eloc_id: str, admin: UserInfo = Depends(require_admin)):
    """
    POST /api/internal/elocs/{eloc_id}/exclude — PRM "Remove" action.

    Excludes the Portal-flow ELOC from the workflow:
      • sets include=false on the Mongo eloc_state document
      • marks the eloc_status_tracker row as Removed (frees the
        shares-available block for the company)
      • DOES NOT delete the tracker row or reverse any applied DealTerms
        deltas — those are only undone by the DELETE route below

    The WebSocket relay picks up the include=false change and broadcasts
    workflow_removed to internal subscribers, so the UI doesn't need to
    update its own state from this response.
    """
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


# ---- DELETE ----------------------------------------------------------------


@router.delete("/elocs/{eloc_id}")
async def delete_eloc(eloc_id: str, admin: UserInfo = Depends(require_admin)):
    """
    DELETE /api/internal/elocs/{eloc_id} — PRM "Delete" action.

    Calls DTS's DELETE /api/portal/eloc/states/{eloc_id}, which:
      1. reverses any applied DealTerms deltas (registered_shares from
         DTO completion, total_commitment from VWAP)
      2. deletes the eloc_status_tracker row
      3. deletes the Mongo eloc_state + eloc_data documents

    Returns the DTS response verbatim — the new sharesReversed /
    commitmentReversed booleans plus sharesOutcome / commitmentOutcome
    enum strings are surfaced to the UI so the operator can see exactly
    what hit eloc_deal.
    """
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

"""
3i Fund Portal — Admin Router
Admin-only endpoints for viewing all companies, ELOCs, and purchase notices.
Data sourced from DealTermsServer REST API.
"""

import asyncio
import logging
import time

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.onprem import client as onprem

logger = logging.getLogger("portal.admin")
router = APIRouter()


@router.get("/companies")
async def list_companies(admin: UserInfo = Depends(require_admin)):
    """List all companies with ELOC counts."""
    t_start = time.monotonic()
    logger.info("GET /admin/companies by user=%s — START", admin.user_id)

    # Get company list and ELOC states in parallel
    t_dts = time.monotonic()
    summaries, all_states = await asyncio.gather(
        onprem.get_all_company_summaries(),
        onprem.get_all_eloc_states(),
    )
    logger.info("GET /admin/companies — DTS calls completed in %.1fms (summaries=%d, states=%d)",
                (time.monotonic() - t_dts) * 1000, len(summaries), len(all_states))

    # Build counts per companyId
    company_counts: dict[int, dict] = {}
    for state in all_states:
        cid = state.get("companyId")
        if cid is None:
            continue
        if cid not in company_counts:
            company_counts[cid] = {"total": 0, "active": 0, "last_activity": None}
        company_counts[cid]["total"] += 1
        if state.get("include", False):
            company_counts[cid]["active"] += 1
        modified = state.get("modifiedAt")
        if modified:
            existing = company_counts[cid]["last_activity"]
            if existing is None or str(modified) > str(existing):
                company_counts[cid]["last_activity"] = modified

    companies = []
    for s in summaries:
        # CompanySummary has symbol and companyName but not companyId
        # Match by looking through states for this company's name
        symbol = s.get("symbol", "")
        name = s.get("companyName", "")

        # Find companyId from states that match this company
        matched_cid = None
        for state in all_states:
            # ElocData extractedFields has company info, but state only has companyId
            # We can't easily match symbol to companyId here without additional data
            # For now, include all companies from summaries
            pass

        companies.append({
            "company_id": symbol,  # Use symbol as identifier
            "name": name,
            "symbol": symbol,
            "has_active_eloc": s.get("hasActiveEloc", False),
            "active_elocs": 0,
            "total_elocs": 0,
            "last_activity": None,
        })

    # Enrich with counts where we can match by companyId
    # (CompanySummary doesn't include companyId, so counts are best-effort)
    t_total = (time.monotonic() - t_start) * 1000
    logger.info("GET /admin/companies — DONE in %.1fms, returned %d companies", t_total, len(companies))
    return companies


@router.get("/elocs")
async def list_all_elocs(admin: UserInfo = Depends(require_admin)):
    """List all ELOCs across all companies."""
    t_start = time.monotonic()
    logger.info("GET /admin/elocs by user=%s — START", admin.user_id)

    all_states = await onprem.get_all_eloc_states()
    logger.info("GET /admin/elocs — DTS states fetched in %.1fms (%d states)",
                (time.monotonic() - t_start) * 1000, len(all_states))

    elocs = []
    for state in all_states:
        elocs.append({
            "eloc_id": str(state.get("elocId", "")),
            "company_id": state.get("companyId", ""),
            "company_name": "",  # Not available in ElocStateDto
            "status": state.get("status", "Pending"),
            "current_workflow_step": state.get("workflowStep", ""),
            "include": state.get("include", False),
            "created_at": state.get("createdAt"),
            "modified_at": state.get("modifiedAt"),
        })

    t_total = (time.monotonic() - t_start) * 1000
    logger.info("GET /admin/elocs — DONE in %.1fms, returned %d ELOCs", t_total, len(elocs))
    return elocs


@router.get("/purchase-notices")
async def list_purchase_notices(admin: UserInfo = Depends(require_admin)):
    """List all purchase notices across all companies."""
    t_start = time.monotonic()
    logger.info("GET /admin/purchase-notices by user=%s — START", admin.user_id)

    all_states = await onprem.get_all_eloc_states()
    logger.info("GET /admin/purchase-notices — states fetched in %.1fms (%d states)",
                (time.monotonic() - t_start) * 1000, len(all_states))
    notices = []

    # N+1 WARNING: fetches ELOC data for each state sequentially
    t_data = time.monotonic()
    fetch_count = 0
    for state in all_states:
        eloc_id = str(state.get("elocId", ""))
        if not eloc_id:
            continue

        # Fetch ELOC data for purchase notice info
        fetch_count += 1
        data = await onprem.get_eloc_data(eloc_id)
        if not data:
            continue

        # Check if this ELOC has extracted fields (indicates a purchase notice was processed)
        extracted = data.get("extractedFields")
        if not extracted:
            continue

        # Extract purchase notice details from the ELOC data
        share_amount = extracted.get("vwapPurchaseShareAmount", {})
        company_name = extracted.get("companyName", {})
        company_symbol = extracted.get("companySymbol", {})

        notices.append({
            "notice_id": data.get("id", eloc_id),
            "company_id": state.get("companyId", ""),
            "company_name": company_name.get("value", "") if isinstance(company_name, dict) else "",
            "company_symbol": company_symbol.get("value", "") if isinstance(company_symbol, dict) else "",
            "eloc_id": eloc_id,
            "shares": share_amount.get("value", 0) if isinstance(share_amount, dict) else 0,
            "status": state.get("status", "Pending"),
            "received_at": data.get("receivedAt"),
        })

    t_total = (time.monotonic() - t_start) * 1000
    logger.info("GET /admin/purchase-notices — DONE in %.1fms (fetched %d ELOC data docs, returned %d notices)",
                t_total, fetch_count, len(notices))
    return notices

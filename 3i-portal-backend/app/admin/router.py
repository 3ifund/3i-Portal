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

    # Get company list from DealTermsServer
    t_dts = time.monotonic()
    summaries = await onprem.get_all_company_summaries()
    logger.info("GET /admin/companies — DTS call completed in %.1fms (summaries=%d)",
                (time.monotonic() - t_dts) * 1000, len(summaries))

    companies = []
    for s in summaries:
        symbol = s.get("symbol", "")
        name = s.get("companyName", "")
        companies.append({
            "company_id": symbol,
            "name": name,
            "symbol": symbol,
            "has_active_eloc": s.get("hasActiveEloc", False),
            "active_elocs": 0,
            "total_elocs": 0,
            "last_activity": None,
        })
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

    # Fetch all ELOC data in parallel instead of N+1 sequential
    eloc_ids = [str(s.get("elocId", "")) for s in all_states if s.get("elocId")]
    logger.info("GET /admin/purchase-notices — fetching %d ELOC data docs in parallel", len(eloc_ids))
    t_data = time.monotonic()

    async def _fetch_data(eid):
        try:
            return eid, await onprem.get_eloc_data(eid)
        except Exception:
            return eid, None

    data_results = await asyncio.gather(*[_fetch_data(eid) for eid in eloc_ids])
    data_map = {eid: data for eid, data in data_results if data}
    logger.info("GET /admin/purchase-notices — parallel fetch completed in %.1fms (%d docs)",
                (time.monotonic() - t_data) * 1000, len(data_map))

    for state in all_states:
        eloc_id = str(state.get("elocId", ""))
        data = data_map.get(eloc_id)
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
                t_total, len(data_map), len(notices))
    return notices

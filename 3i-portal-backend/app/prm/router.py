"""
3i Fund Portal — PRM (Positions & Traders) Router.

Admin-only REST endpoints that back the position_risk_management web app's
P&T view (the Synthetic Trade mirror). Thin proxies over the DTS `app.onprem`
client — DTS owns the connection to PRM's Positions & Traders PostgreSQL DB.

Slice 1 is READ-ONLY (companies + firm common-stock positions). The atomic
trade write operations arrive in a later slice. Mounted at /api/internal/prm
so CloudFront forwards it (only /api/* and /ws/* reach the origin).
"""

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.onprem import client as onprem

logger = logging.getLogger("portal.prm")
router = APIRouter()


@router.get("/companies")
async def list_companies(admin: UserInfo = Depends(require_admin)):
    """
    GET /api/internal/prm/companies — every company (for the Synthetic Trade
    company picker). Proxies DTS GET /api/companies.
    """
    t_start = time.monotonic()
    logger.info("GET /internal/prm/companies by user=%s — START", admin.user_id)
    try:
        companies = await onprem.get_prm_companies()
    except Exception as exc:
        logger.error("GET /internal/prm/companies — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")

    t_total = (time.monotonic() - t_start) * 1000
    logger.info(
        "GET /internal/prm/companies — DONE in %.1fms (count=%d, user=%s)",
        t_total, len(companies) if companies else 0, admin.user_id,
    )
    return companies


@router.get("/positions/common")
async def list_common_positions(
    company_id: int = Query(..., description="PRM companyid"),
    admin: UserInfo = Depends(require_admin),
):
    """
    GET /api/internal/prm/positions/common?company_id= — firm common-stock
    positions for a company. Proxies DTS GET /api/prm/positions/common.
    """
    t_start = time.monotonic()
    logger.info(
        "GET /internal/prm/positions/common company_id=%s by user=%s — START",
        company_id, admin.user_id,
    )
    if company_id <= 0:
        raise HTTPException(status_code=400, detail="company_id must be > 0")

    try:
        positions = await onprem.get_prm_common_positions(company_id)
    except Exception as exc:
        logger.error(
            "GET /internal/prm/positions/common company_id=%s — DTS fetch FAILED: %s",
            company_id, exc, exc_info=True,
        )
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")

    t_total = (time.monotonic() - t_start) * 1000
    logger.info(
        "GET /internal/prm/positions/common company_id=%s — DONE in %.1fms (count=%d, user=%s)",
        company_id, t_total, len(positions) if positions else 0, admin.user_id,
    )
    return positions

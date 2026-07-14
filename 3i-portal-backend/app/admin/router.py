
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
    t_start = time.monotonic()
    logger.info("GET /admin/companies by user=%s — START", admin.user_id)

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

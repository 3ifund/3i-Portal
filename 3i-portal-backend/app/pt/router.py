import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.onprem import client as onprem

logger = logging.getLogger("portal.pt")
router = APIRouter()


class OverTheWallBody(BaseModel):
    overTheWall: bool
    userName: str | None = None


@router.get("/companies")
async def get_companies(admin: UserInfo = Depends(require_admin)):
    try:
        return await onprem.get_pt_companies()
    except Exception as exc:
        logger.error("companies — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.get("/allocations")
async def get_allocations(traderId: int, admin: UserInfo = Depends(require_admin)):
    try:
        return await onprem.get_pt_allocations(traderId)
    except Exception as exc:
        logger.error("allocations — DTS fetch FAILED (traderId=%s): %s", traderId, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.get("/open-orders")
async def get_open_orders(traderId: int, companyId: int, admin: UserInfo = Depends(require_admin)):
    try:
        return await onprem.get_pt_open_orders(traderId, companyId)
    except Exception as exc:
        logger.error("open-orders — DTS fetch FAILED (traderId=%s, companyId=%s): %s", traderId, companyId, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.get("/order-log")
async def get_order_log(traderId: int, symbol: str, period: str | None = None, admin: UserInfo = Depends(require_admin)):
    try:
        return await onprem.get_pt_order_log(traderId, symbol, period)
    except Exception as exc:
        logger.error("order-log — DTS fetch FAILED (traderId=%s, symbol=%s): %s", traderId, symbol, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.get("/non-trading")
async def get_non_trading(companyId: int, symbol: str, period: str | None = None, admin: UserInfo = Depends(require_admin)):
    try:
        return await onprem.get_pt_non_trading(companyId, symbol, period)
    except Exception as exc:
        logger.error("non-trading — DTS fetch FAILED (companyId=%s, symbol=%s): %s", companyId, symbol, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.get("/traders")
async def get_traders(companyId: int | None = None, admin: UserInfo = Depends(require_admin)):
    try:
        return await onprem.get_pt_traders(companyId)
    except Exception as exc:
        logger.error("traders — DTS fetch FAILED (companyId=%s): %s", companyId, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.put("/companies/{company_id}/over-the-wall")
async def set_over_the_wall(company_id: int, body: OverTheWallBody, admin: UserInfo = Depends(require_admin)):
    payload = body.model_dump()
    if not payload.get("userName"):
        payload["userName"] = admin.user_id
    logger.info("PUT /internal/pt/companies/%s/over-the-wall -> %s by user=%s", company_id, payload["overTheWall"], admin.user_id)
    try:
        return await onprem.set_pt_company_over_the_wall(company_id, payload)
    except Exception as exc:
        logger.error("over-the-wall — DTS FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")

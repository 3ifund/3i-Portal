"""
3i Fund Portal — Convertible-note Conversions router.

Admin-only endpoints backing the position_risk_management CONV view. Thin proxies over the DTS
app.onprem client (DTS owns the note registry + the PRM conversions). The per-company convert-lock
owner is stamped server-side with the authenticated admin — never taken from the client. DTS status
codes (200 / 400 business reject / 409 lock held) are passed through verbatim. Mounted at
/api/internal/conversions so CloudFront forwards it (only /api/* and /ws/* reach the origin).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.onprem import client as onprem

logger = logging.getLogger("portal.conversions")
router = APIRouter()


class LockBody(BaseModel):
    company: str


class ConvertBody(BaseModel):
    company: str
    price: float
    amount: float


@router.get("/aggregates")
async def get_aggregates(admin: UserInfo = Depends(require_admin)):
    logger.info("GET /internal/conversions/aggregates by user=%s", admin.user_id)
    try:
        return await onprem.get_conversion_aggregates()
    except Exception as exc:
        logger.error("aggregates — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.get("/lock/{company}")
async def get_lock(company: str, admin: UserInfo = Depends(require_admin)):
    logger.info("GET /internal/conversions/lock/%s by user=%s", company, admin.user_id)
    try:
        return await onprem.get_conversion_lock(company)
    except Exception as exc:
        logger.error("lock-state — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.post("/lock")
async def acquire_lock(body: LockBody, admin: UserInfo = Depends(require_admin)):
    logger.info("POST /internal/conversions/lock company=%s owner=%s", body.company, admin.user_id)
    status, data = await onprem.acquire_conversion_lock({"company": body.company, "owner": admin.user_id})
    return JSONResponse(status_code=status, content=data)


@router.post("/unlock")
async def release_lock(body: LockBody, admin: UserInfo = Depends(require_admin)):
    logger.info("POST /internal/conversions/unlock company=%s owner=%s", body.company, admin.user_id)
    status, data = await onprem.release_conversion_lock({"company": body.company, "owner": admin.user_id})
    return JSONResponse(status_code=status, content=data)


@router.post("/convert")
async def convert(body: ConvertBody, admin: UserInfo = Depends(require_admin)):
    logger.info(
        "POST /internal/conversions/convert company=%s price=%s amount=%s owner=%s",
        body.company, body.price, body.amount, admin.user_id,
    )
    status, data = await onprem.convert_basic(
        {"company": body.company, "price": body.price, "amount": body.amount, "owner": admin.user_id}
    )
    return JSONResponse(status_code=status, content=data)

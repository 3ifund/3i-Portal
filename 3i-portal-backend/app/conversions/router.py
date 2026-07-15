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


class Allow144Body(BaseModel):
    company: str
    allow: bool


class TradingObjectiveBody(BaseModel):
    company: str
    objective: str


@router.get("/aggregates")
async def get_aggregates(admin: UserInfo = Depends(require_admin)):
    logger.info("GET /internal/conversions/aggregates by user=%s", admin.user_id)
    try:
        return await onprem.get_conversion_aggregates()
    except Exception as exc:
        logger.error("aggregates — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.get("/rule144")
async def get_rule144(admin: UserInfo = Depends(require_admin)):
    logger.info("GET /internal/conversions/rule144 by user=%s", admin.user_id)
    try:
        return await onprem.get_conversion_rule144()
    except Exception as exc:
        logger.error("rule144 — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.post("/rule144/allow")
async def set_allow144(body: Allow144Body, admin: UserInfo = Depends(require_admin)):
    logger.info("POST /internal/conversions/rule144/allow company=%s allow=%s by user=%s",
                body.company, body.allow, admin.user_id)
    status, data = await onprem.set_conversion_allow144({"company": body.company, "allow": body.allow})
    return JSONResponse(status_code=status, content=data)


@router.post("/trading-objective")
async def set_trading_objective(body: TradingObjectiveBody, admin: UserInfo = Depends(require_admin)):
    logger.info("POST /internal/conversions/trading-objective company=%s objective=%s by user=%s",
                body.company, body.objective, admin.user_id)
    status, data = await onprem.set_conversion_trading_objective({"company": body.company, "objective": body.objective})
    return JSONResponse(status_code=status, content=data)


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

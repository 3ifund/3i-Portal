import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.onprem import client as onprem

logger = logging.getLogger("portal.preferred")
router = APIRouter()


class ConvertBody(BaseModel):
    instrumentId: int
    conversionType: str = "Variable"
    amount: float


class AllowTrueUpBody(BaseModel):
    companyId: int
    allow: bool


class TradingObjectiveBody(BaseModel):
    companyId: int
    objective: str


@router.get("/companies")
async def get_companies(admin: UserInfo = Depends(require_admin)):
    logger.info("GET /internal/preferred/companies by user=%s", admin.user_id)
    try:
        return await onprem.get_preferred_companies()
    except Exception as exc:
        logger.error("preferred companies — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.get("/preview")
async def get_preview(instrumentId: int, amount: float, conversionType: str = "Variable",
                      admin: UserInfo = Depends(require_admin)):
    logger.info("GET /internal/preferred/preview instrumentId=%s amount=%s type=%s by user=%s",
                instrumentId, amount, conversionType, admin.user_id)
    try:
        return await onprem.get_preferred_preview(instrumentId, amount, conversionType)
    except Exception as exc:
        # DTS rejects bad/partial params with 4xx — an expected, keystroke-driven condition, not an outage.
        logger.warning("preferred preview — DTS returned error: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/completed/{company_id}")
async def get_completed(company_id: int, admin: UserInfo = Depends(require_admin)):
    logger.info("GET /internal/preferred/completed/%s by user=%s", company_id, admin.user_id)
    try:
        return await onprem.get_preferred_completed(company_id)
    except Exception as exc:
        logger.error("preferred completed — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.post("/convert")
async def convert(body: ConvertBody, admin: UserInfo = Depends(require_admin)):
    logger.info("POST /internal/preferred/convert instrumentId=%s type=%s amount=%s owner=%s",
                body.instrumentId, body.conversionType, body.amount, admin.user_id)
    status, data = await onprem.preferred_convert({
        "instrumentId": body.instrumentId,
        "conversionType": body.conversionType,
        "dollarAmount": body.amount,
        "owner": admin.user_id,
    })
    return JSONResponse(status_code=status, content=data)


@router.post("/true-ups/allow")
async def set_allow_true_up(body: AllowTrueUpBody, admin: UserInfo = Depends(require_admin)):
    logger.info("POST /internal/preferred/true-ups/allow company=%s allow=%s by user=%s",
                body.companyId, body.allow, admin.user_id)
    status, data = await onprem.set_preferred_allow_true_up({"companyId": body.companyId, "allow": body.allow})
    return JSONResponse(status_code=status, content=data)


@router.post("/trading-objective")
async def set_trading_objective(body: TradingObjectiveBody, admin: UserInfo = Depends(require_admin)):
    logger.info("POST /internal/preferred/trading-objective company=%s objective=%s by user=%s",
                body.companyId, body.objective, admin.user_id)
    status, data = await onprem.set_preferred_trading_objective({"companyId": body.companyId, "objective": body.objective})
    return JSONResponse(status_code=status, content=data)


@router.delete("/{conversion_id}")
async def delete_conversion(conversion_id: str, admin: UserInfo = Depends(require_admin)):
    logger.info("DELETE /internal/preferred/%s by user=%s", conversion_id, admin.user_id)
    status, data = await onprem.delete_preferred_conversion(conversion_id)
    return JSONResponse(status_code=status, content=data)

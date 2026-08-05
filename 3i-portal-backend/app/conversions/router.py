import logging

import httpx
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


@router.get("/preview")
async def get_preview(company: str, price: float, amount: float, admin: UserInfo = Depends(require_admin)):
    logger.info(
        "GET /internal/conversions/preview company=%s price=%s amount=%s by user=%s",
        company, price, amount, admin.user_id,
    )
    if price <= 0 or amount <= 0:
        # This endpoint is fired on every debounced keystroke; a zero/negative amount or price is a normal
        # intermediate state, not an outage — short-circuit before a wasted DTS round-trip.
        logger.info("preview — skipped (price=%s amount=%s not both > 0)", price, amount)
        raise HTTPException(status_code=422, detail="price and amount must both be greater than 0")
    try:
        return await onprem.get_conversion_preview(company, price, amount, include_pdf=False)
    except httpx.HTTPStatusError as exc:
        # DTS rejected the input (bad/partial params) — an expected, keystroke-driven condition, not a server
        # failure. Pass the real status/message through so the UI can show an inline hint, and log at info (no trace).
        logger.info("preview — DTS rejected input (%s): %s", exc.response.status_code, exc.response.text[:500])
        raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text[:500])
    except Exception as exc:
        logger.error("preview — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.get("/recalc-window")
async def get_recalc_window(admin: UserInfo = Depends(require_admin)):
    logger.info("GET /internal/conversions/recalc-window by user=%s", admin.user_id)
    try:
        return await onprem.get_conversion_recalc_window()
    except Exception as exc:
        logger.error("recalc-window — DTS fetch FAILED: %s", exc, exc_info=True)
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


@router.get("/brokers-with-accounts")
async def get_brokers_with_accounts(admin: UserInfo = Depends(require_admin)):
    logger.info("GET /internal/conversions/brokers-with-accounts by user=%s", admin.user_id)
    try:
        return await onprem.get_brokers_with_accounts()
    except Exception as exc:
        logger.error("brokers-with-accounts — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


class NoteBrokerAccountBody(BaseModel):
    brokerId: int
    accountId: int


@router.put("/notes/{instrument_id}/broker-account")
async def set_note_broker_account(instrument_id: int, body: NoteBrokerAccountBody, admin: UserInfo = Depends(require_admin)):
    logger.info("PUT /internal/conversions/notes/%s/broker-account broker=%s account=%s by user=%s",
                instrument_id, body.brokerId, body.accountId, admin.user_id)
    status, data = await onprem.set_note_broker_account(instrument_id, {"brokerId": body.brokerId, "accountId": body.accountId})
    return JSONResponse(status_code=status, content=data)


@router.post("/acceleration-true-ups/allow")
async def set_acceleration_true_ups(body: Allow144Body, admin: UserInfo = Depends(require_admin)):
    logger.info("POST /internal/conversions/acceleration-true-ups/allow company=%s allow=%s by user=%s",
                body.company, body.allow, admin.user_id)
    status, data = await onprem.set_conversion_acceleration_true_ups({"company": body.company, "allow": body.allow})
    return JSONResponse(status_code=status, content=data)


@router.post("/installment-true-ups/allow")
async def set_installment_true_ups(body: Allow144Body, admin: UserInfo = Depends(require_admin)):
    logger.info("POST /internal/conversions/installment-true-ups/allow company=%s allow=%s by user=%s",
                body.company, body.allow, admin.user_id)
    status, data = await onprem.set_conversion_installment_true_ups({"company": body.company, "allow": body.allow})
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


@router.get("/completed/{company}")
async def get_completed(company: str, admin: UserInfo = Depends(require_admin)):
    logger.info("GET /internal/conversions/completed/%s by user=%s", company, admin.user_id)
    try:
        return await onprem.get_conversion_completed(company)
    except Exception as exc:
        logger.error("completed — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.get("/{conversion_id}/pdf/{notice_index}/{doc_type}")
async def get_pdf(conversion_id: str, notice_index: int, doc_type: str, admin: UserInfo = Depends(require_admin)):
    logger.info("GET /internal/conversions/%s/pdf/%s/%s by user=%s", conversion_id, notice_index, doc_type, admin.user_id)
    try:
        return await onprem.get_conversion_pdf(conversion_id, notice_index, doc_type)
    except Exception as exc:
        logger.error("pdf — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.delete("/{conversion_id}")
async def delete_conversion(conversion_id: str, admin: UserInfo = Depends(require_admin)):
    logger.info("DELETE /internal/conversions/%s by user=%s", conversion_id, admin.user_id)
    status, data = await onprem.delete_conversion(conversion_id)
    return JSONResponse(status_code=status, content=data)


@router.post("/{conversion_id}/remove")
async def remove_conversion(conversion_id: str, admin: UserInfo = Depends(require_admin)):
    logger.info("POST /internal/conversions/%s/remove by user=%s", conversion_id, admin.user_id)
    status, data = await onprem.remove_conversion(conversion_id)
    return JSONResponse(status_code=status, content=data)

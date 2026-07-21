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


class TraderActionBody(BaseModel):
    userName: str | None = None


_TRADER_ACTIONS = {"block", "unblock", "cancel-all"}


@router.post("/traders/{trader_id}/{action}")
async def trader_action(trader_id: int, action: str, body: TraderActionBody | None = None, admin: UserInfo = Depends(require_admin)):
    if action not in _TRADER_ACTIONS:
        raise HTTPException(status_code=404, detail=f"Unknown trader action '{action}'")
    payload = {"userName": (body.userName if body else None) or admin.user_id}
    logger.info("POST /internal/pt/traders/%s/%s by user=%s", trader_id, action, admin.user_id)
    try:
        status, data = await onprem.post_pt_trader_action(trader_id, action, payload)
        if status >= 400:
            raise HTTPException(status_code=status, detail=data.get("error") or data.get("message") or "DTS error")
        return data
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("trader action %s/%s — DTS FAILED: %s", trader_id, action, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.get("/companies")
async def get_companies(admin: UserInfo = Depends(require_admin)):
    try:
        return await onprem.get_pt_companies()
    except Exception as exc:
        logger.error("companies — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


class TraderCreateBody(BaseModel):
    name: str
    reduceRisk: bool = False


class TraderSaveBody(BaseModel):
    name: str
    reduceRisk: bool = False
    brokerIds: list[int] = []
    accountIds: list[int] = []
    defaultAccountId: int | None = None


@router.get("/trader-mgmt/traders")
async def tm_get_traders(admin: UserInfo = Depends(require_admin)):
    try:
        return await onprem.get_tm_traders()
    except Exception as exc:
        logger.error("trader-mgmt traders — DTS FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.get("/trader-mgmt/brokers")
async def tm_get_brokers(admin: UserInfo = Depends(require_admin)):
    try:
        return await onprem.get_tm_brokers()
    except Exception as exc:
        logger.error("trader-mgmt brokers — DTS FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.get("/trader-mgmt/brokers/{broker_id}/accounts")
async def tm_get_broker_accounts(broker_id: int, admin: UserInfo = Depends(require_admin)):
    try:
        return await onprem.get_tm_broker_accounts(broker_id)
    except Exception as exc:
        logger.error("trader-mgmt broker accounts — DTS FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.get("/trader-mgmt/traders/{trader_id}")
async def tm_get_trader(trader_id: int, admin: UserInfo = Depends(require_admin)):
    try:
        return await onprem.get_tm_trader(trader_id)
    except Exception as exc:
        logger.error("trader-mgmt trader %s — DTS FAILED: %s", trader_id, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.post("/trader-mgmt/traders")
async def tm_create_trader(body: TraderCreateBody, admin: UserInfo = Depends(require_admin)):
    logger.info("POST /internal/pt/trader-mgmt/traders name=%s by user=%s", body.name, admin.user_id)
    try:
        status, data = await onprem.create_tm_trader(body.model_dump())
        if status >= 400:
            raise HTTPException(status_code=status, detail=data.get("error") or data.get("message") or "DTS error")
        return data
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("trader-mgmt create — DTS FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.put("/trader-mgmt/traders/{trader_id}")
async def tm_save_trader(trader_id: int, body: TraderSaveBody, admin: UserInfo = Depends(require_admin)):
    logger.info("PUT /internal/pt/trader-mgmt/traders/%s by user=%s", trader_id, admin.user_id)
    try:
        status, data = await onprem.save_tm_trader(trader_id, body.model_dump())
        if status >= 400:
            raise HTTPException(status_code=status, detail=data.get("error") or data.get("message") or "DTS error")
        return data
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("trader-mgmt save %s — DTS FAILED: %s", trader_id, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.delete("/trader-mgmt/traders/{trader_id}")
async def tm_delete_trader(trader_id: int, admin: UserInfo = Depends(require_admin)):
    logger.info("DELETE /internal/pt/trader-mgmt/traders/%s by user=%s", trader_id, admin.user_id)
    try:
        status, data = await onprem.delete_tm_trader(trader_id)
        if status >= 400:
            raise HTTPException(status_code=status, detail=data.get("error") or data.get("message") or "DTS error")
        return data
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("trader-mgmt delete %s — DTS FAILED: %s", trader_id, exc, exc_info=True)
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


class UserNameBody(BaseModel):
    userName: str | None = None


@router.get("/user-settings")
async def get_user_settings(admin: UserInfo = Depends(require_admin)):
    # The display name is keyed by the authenticated portal user — never trust a client-supplied key.
    try:
        return await onprem.get_pt_user_settings(admin.user_id)
    except Exception as exc:
        logger.error("user-settings get — DTS FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.put("/user-settings")
async def set_user_settings(body: UserNameBody, admin: UserInfo = Depends(require_admin)):
    logger.info("PUT /internal/pt/user-settings by user=%s -> %s", admin.user_id, body.userName)
    try:
        return await onprem.set_pt_user_settings(admin.user_id, body.userName)
    except Exception as exc:
        logger.error("user-settings put — DTS FAILED: %s", exc, exc_info=True)
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

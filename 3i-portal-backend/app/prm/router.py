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
from pydantic import BaseModel

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.onprem import client as onprem

logger = logging.getLogger("portal.prm")
router = APIRouter()


class SyntheticTradeBody(BaseModel):
    """Slice-2 Unrestricted synthetic trade from the P&T web app. TraderIdentifier
    is NOT accepted from the client — it's stamped server-side with the admin."""
    company_id: int
    symbol: str
    position_id: int = 0
    is_buy: bool
    quantity: int
    price: float = 0
    account_id: int
    broker_id: int
    source: str | None = "SYNTHETIC"


class RestrictedTradeBody(BaseModel):
    """Restricted-pool BUY/SELL. TraderIdentifier stamped server-side."""
    company_id: int
    symbol: str
    position_id: int
    is_buy: bool
    quantity: int
    price: float = 0


class TransferBody(BaseModel):
    """Move shares restricted ↔ unrestricted. TraderIdentifier stamped server-side."""
    company_id: int
    symbol: str
    position_id: int
    quantity: int
    account_id: int
    broker_id: int
    is_restricted_to_unrestricted: bool


class AddInstrumentBody(BaseModel):
    """Create a new instrument/position (Position=0). Mirrors AddInstrumentDialog."""
    instrument_type: str  # "Common Stock" | "Preferred" | "Warrant" | "Convertible"
    company_id: int
    symbol: str
    dividend_rate: float | None = None
    par_value: float | None = None
    is_convertible: bool = False
    strike: float | None = None
    expiration: str | None = None  # ISO date
    maturity: str | None = None    # ISO date
    coupon: float | None = None
    conversion_price: float | None = None
    conversion_ratio: float | None = None


class DerivativeTradeBody(BaseModel):
    """Legacy BUY/SELL for Preferred/Warrant/Convertible. Trader stamped server-side."""
    instrument_type: str  # "Preferred" | "Warrant" | "Convertible"
    company_id: int
    symbol: str
    position_id: int
    is_buy: bool
    quantity: int
    price: float = 0


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


@router.get("/positions/{position_id}/accounts")
async def list_position_accounts(
    position_id: int,
    admin: UserInfo = Depends(require_admin),
):
    """
    GET /api/internal/prm/positions/{position_id}/accounts — account/broker
    allocations for a position (Synthetic Trade pickers). Proxies DTS.
    """
    t_start = time.monotonic()
    logger.info("GET /internal/prm/positions/%s/accounts by user=%s — START", position_id, admin.user_id)
    if position_id <= 0:
        raise HTTPException(status_code=400, detail="position_id must be > 0")
    try:
        accounts = await onprem.get_prm_position_accounts(position_id)
    except Exception as exc:
        logger.error("GET /internal/prm/positions/%s/accounts — DTS fetch FAILED: %s", position_id, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")
    logger.info(
        "GET /internal/prm/positions/%s/accounts — DONE in %.1fms (count=%d)",
        position_id, (time.monotonic() - t_start) * 1000, len(accounts) if accounts else 0,
    )
    return accounts


@router.post("/synthetic-trade")
async def execute_synthetic_trade(
    body: SyntheticTradeBody,
    admin: UserInfo = Depends(require_admin),
):
    """
    POST /api/internal/prm/synthetic-trade — execute a manual Unrestricted
    synthetic trade. WRITE. The trader identity is stamped from the
    authenticated admin (never the client). Proxies DTS
    POST /api/prm/positions/synthetic-trade.
    """
    t_start = time.monotonic()
    side = "BUY" if body.is_buy else "SELL"
    logger.info(
        "POST /internal/prm/synthetic-trade by user=%s — %s %s %s @ %s positionId=%s acct=%s broker=%s — START",
        admin.user_id, side, body.quantity, body.symbol, body.price, body.position_id, body.account_id, body.broker_id,
    )
    if body.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be > 0")
    if body.account_id <= 0 or body.broker_id <= 0:
        raise HTTPException(status_code=400, detail="account_id and broker_id are required")

    payload = {
        "companyId": body.company_id,
        "symbol": body.symbol,
        "positionId": body.position_id,
        "isBuy": body.is_buy,
        "quantity": body.quantity,
        "price": body.price,
        "accountId": body.account_id,
        "brokerId": body.broker_id,
        "source": body.source or "SYNTHETIC",
        # Server-stamped identity for the positiontransaction audit trail.
        "traderIdentifier": admin.user_id,
    }

    try:
        status_code, result = await onprem.post_prm_synthetic_trade(payload)
    except Exception as exc:
        logger.error("POST /internal/prm/synthetic-trade — DTS call FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")

    t_total = (time.monotonic() - t_start) * 1000
    if status_code == 200:
        logger.info(
            "POST /internal/prm/synthetic-trade — DONE in %.1fms (user=%s, %s, txnId=%s)",
            t_total, admin.user_id, result.get("message"), result.get("transactionId"),
        )
        return result

    # Surface a DTS business rejection (e.g. oversell) as a 400 with its message;
    # anything else is an upstream failure.
    msg = (result or {}).get("message") or "Synthetic trade failed"
    if status_code == 400:
        logger.warning("POST /internal/prm/synthetic-trade — REJECTED (%.1fms): %s", t_total, msg)
        raise HTTPException(status_code=400, detail=msg)
    logger.error("POST /internal/prm/synthetic-trade — DTS status=%s: %s", status_code, msg)
    raise HTTPException(status_code=502, detail=f"DTS error ({status_code}): {msg}")


def _surface(label: str, status_code: int, result: dict, t_total: float):
    """Map a DTS (status, body) write result to a FastAPI response/exception."""
    if status_code == 200:
        logger.info("%s — DONE in %.1fms (%s, txnId=%s)", label, t_total, result.get("message"), result.get("transactionId"))
        return result
    msg = (result or {}).get("message") or "Operation failed"
    if status_code == 400:
        logger.warning("%s — REJECTED (%.1fms): %s", label, t_total, msg)
        raise HTTPException(status_code=400, detail=msg)
    logger.error("%s — DTS status=%s: %s", label, status_code, msg)
    raise HTTPException(status_code=502, detail=f"DTS error ({status_code}): {msg}")


@router.post("/restricted-trade")
async def execute_restricted_trade(
    body: RestrictedTradeBody,
    admin: UserInfo = Depends(require_admin),
):
    """
    POST /api/internal/prm/restricted-trade — BUY/SELL on the restricted pool.
    WRITE. Proxies DTS POST /api/prm/positions/restricted-trade.
    """
    t_start = time.monotonic()
    act = "ADD" if body.is_buy else "REMOVE"
    logger.info(
        "POST /internal/prm/restricted-trade by user=%s — %s %s %s positionId=%s @ %s — START",
        admin.user_id, act, body.quantity, body.symbol, body.position_id, body.price,
    )
    if body.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be > 0")
    payload = {
        "companyId": body.company_id,
        "symbol": body.symbol,
        "positionId": body.position_id,
        "isBuy": body.is_buy,
        "quantity": body.quantity,
        "price": body.price,
        "traderIdentifier": admin.user_id,
    }
    try:
        status_code, result = await onprem.post_prm_restricted_trade(payload)
    except Exception as exc:
        logger.error("POST /internal/prm/restricted-trade — DTS call FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")
    return _surface("POST /internal/prm/restricted-trade", status_code, result, (time.monotonic() - t_start) * 1000)


@router.post("/transfer")
async def execute_transfer(
    body: TransferBody,
    admin: UserInfo = Depends(require_admin),
):
    """
    POST /api/internal/prm/transfer — move shares restricted ↔ unrestricted.
    WRITE. Proxies DTS POST /api/prm/positions/transfer.
    """
    t_start = time.monotonic()
    direction = "R->U" if body.is_restricted_to_unrestricted else "U->R"
    logger.info(
        "POST /internal/prm/transfer by user=%s — %s %s %s positionId=%s acct=%s broker=%s — START",
        admin.user_id, direction, body.quantity, body.symbol, body.position_id, body.account_id, body.broker_id,
    )
    if body.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be > 0")
    if body.account_id <= 0 or body.broker_id <= 0:
        raise HTTPException(status_code=400, detail="account_id and broker_id are required")
    payload = {
        "companyId": body.company_id,
        "symbol": body.symbol,
        "positionId": body.position_id,
        "quantity": body.quantity,
        "accountId": body.account_id,
        "brokerId": body.broker_id,
        "isRestrictedToUnrestricted": body.is_restricted_to_unrestricted,
        "traderIdentifier": admin.user_id,
    }
    try:
        status_code, result = await onprem.post_prm_transfer(payload)
    except Exception as exc:
        logger.error("POST /internal/prm/transfer — DTS call FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")
    return _surface("POST /internal/prm/transfer", status_code, result, (time.monotonic() - t_start) * 1000)


async def _list_positions(kind: str, company_id: int, fetch, admin: UserInfo):
    t_start = time.monotonic()
    logger.info("GET /internal/prm/positions/%s company_id=%s by user=%s — START", kind, company_id, admin.user_id)
    if company_id <= 0:
        raise HTTPException(status_code=400, detail="company_id must be > 0")
    try:
        rows = await fetch(company_id)
    except Exception as exc:
        logger.error("GET /internal/prm/positions/%s company_id=%s — DTS fetch FAILED: %s", kind, company_id, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")
    logger.info("GET /internal/prm/positions/%s company_id=%s — DONE in %.1fms (count=%d)",
                kind, company_id, (time.monotonic() - t_start) * 1000, len(rows) if rows else 0)
    return rows


@router.get("/positions/preferred")
async def list_preferred(company_id: int = Query(...), admin: UserInfo = Depends(require_admin)):
    return await _list_positions("preferred", company_id, onprem.get_prm_preferred_positions, admin)


@router.get("/positions/warrant")
async def list_warrant(company_id: int = Query(...), admin: UserInfo = Depends(require_admin)):
    return await _list_positions("warrant", company_id, onprem.get_prm_warrant_positions, admin)


@router.get("/positions/convertible")
async def list_convertible(company_id: int = Query(...), admin: UserInfo = Depends(require_admin)):
    return await _list_positions("convertible", company_id, onprem.get_prm_convertible_positions, admin)


@router.post("/add")
async def add_instrument(body: AddInstrumentBody, admin: UserInfo = Depends(require_admin)):
    """
    POST /api/internal/prm/add — create a new instrument/position (Position=0).
    WRITE. Proxies DTS POST /api/prm/positions/add.
    """
    t_start = time.monotonic()
    logger.info("POST /internal/prm/add by user=%s — type='%s' symbol=%s companyId=%s — START",
                admin.user_id, body.instrument_type, body.symbol, body.company_id)
    if not body.symbol or not body.symbol.strip():
        raise HTTPException(status_code=400, detail="symbol is required")
    payload = {
        "instrumentType": body.instrument_type,
        "companyId": body.company_id,
        "symbol": body.symbol,
        "dividendRate": body.dividend_rate,
        "parValue": body.par_value,
        "isConvertible": body.is_convertible,
        "strike": body.strike,
        "expiration": body.expiration,
        "maturity": body.maturity,
        "coupon": body.coupon,
        "conversionPrice": body.conversion_price,
        "conversionRatio": body.conversion_ratio,
    }
    try:
        status_code, result = await onprem.post_prm_add_instrument(payload)
    except Exception as exc:
        logger.error("POST /internal/prm/add — DTS call FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")
    return _surface("POST /internal/prm/add", status_code, result, (time.monotonic() - t_start) * 1000)


@router.post("/derivative-trade")
async def execute_derivative_trade(body: DerivativeTradeBody, admin: UserInfo = Depends(require_admin)):
    """
    POST /api/internal/prm/derivative-trade — legacy BUY/SELL for Preferred/
    Warrant/Convertible. WRITE. Proxies DTS POST /api/prm/positions/derivative-trade.
    """
    t_start = time.monotonic()
    side = "BUY" if body.is_buy else "SELL"
    logger.info("POST /internal/prm/derivative-trade by user=%s — %s %s %s %s positionId=%s @ %s — START",
                admin.user_id, body.instrument_type, side, body.quantity, body.symbol, body.position_id, body.price)
    if body.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be > 0")
    payload = {
        "instrumentType": body.instrument_type,
        "companyId": body.company_id,
        "symbol": body.symbol,
        "positionId": body.position_id,
        "isBuy": body.is_buy,
        "quantity": body.quantity,
        "price": body.price,
        "traderIdentifier": admin.user_id,
    }
    try:
        status_code, result = await onprem.post_prm_derivative_trade(payload)
    except Exception as exc:
        logger.error("POST /internal/prm/derivative-trade — DTS call FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")
    return _surface("POST /internal/prm/derivative-trade", status_code, result, (time.monotonic() - t_start) * 1000)

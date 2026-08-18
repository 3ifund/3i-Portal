
import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger("portal.onprem")
_client: httpx.AsyncClient | None = None

MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 2
MAX_RETRY_DELAY = 15


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        logger.info("Creating on-prem HTTP client → %s (timeout=%ss)", settings.onprem_base_url, settings.onprem_timeout_seconds)
        _client = httpx.AsyncClient(
            base_url=settings.onprem_base_url,
            timeout=settings.onprem_timeout_seconds,
        )
    return _client


async def warm_client():
    import time
    t_start = time.monotonic()
    logger.info("Warming on-prem HTTP client → %s", settings.onprem_base_url)
    client = _get_client()
    try:
        response = await client.get("/api/companies")
        t_elapsed = (time.monotonic() - t_start) * 1000
        logger.info("On-prem client warm-up complete: %s in %.1fms", response.status_code, t_elapsed)
    except Exception as exc:
        t_elapsed = (time.monotonic() - t_start) * 1000
        logger.warning("On-prem client warm-up failed (%.1fms): %s — will retry on first request", t_elapsed, exc)


async def _request_with_retry(method: str, url: str, **kwargs) -> httpx.Response:
    import time
    client = _get_client()
    delay = INITIAL_RETRY_DELAY
    t_start = time.monotonic()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            t_req = time.monotonic()
            response = await client.request(method, url, **kwargs)
            t_req_elapsed = (time.monotonic() - t_req) * 1000
            if response.status_code >= 500 and attempt < MAX_RETRIES:
                logger.warning(
                    "  → %s %s returned %s in %.1fms (attempt %d/%d, retry in %ds)",
                    method, url, response.status_code, t_req_elapsed, attempt, MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, MAX_RETRY_DELAY)
                continue
            t_total = (time.monotonic() - t_start) * 1000
            logger.info("  → %s %s → %s in %.1fms (total %.1fms, attempt %d)",
                        method, url, response.status_code, t_req_elapsed, t_total, attempt)
            return response
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, OSError) as exc:
            t_req_elapsed = (time.monotonic() - t_req) * 1000
            if attempt == MAX_RETRIES:
                t_total = (time.monotonic() - t_start) * 1000
                logger.error(
                    "  → %s %s failed after %d attempts in %.1fms: %s",
                    method, url, MAX_RETRIES, t_total, exc,
                )
                raise
            logger.warning(
                "  → %s %s failed in %.1fms (attempt %d/%d): %s (retry in %ds)",
                method, url, t_req_elapsed, attempt, MAX_RETRIES, exc, delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, MAX_RETRY_DELAY)

    raise httpx.ConnectError(f"Failed after {MAX_RETRIES} attempts")



async def get_included_eloc_states() -> list[dict]:
    logger.info("GET /api/eloc/states/included")
    response = await _request_with_retry("GET", "/api/eloc/states/included")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_prm_companies() -> list[dict]:
    logger.info("GET /api/prm/positions/companies")
    response = await _request_with_retry("GET", "/api/prm/positions/companies")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_prm_common_positions(company_id: int) -> list[dict]:
    logger.info("GET /api/prm/positions/common?companyId=%s", company_id)
    response = await _request_with_retry(
        "GET", "/api/prm/positions/common", params={"companyId": company_id}
    )
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_prm_position_accounts(position_id: int) -> list[dict]:
    logger.info("GET /api/prm/positions/%s/accounts", position_id)
    response = await _request_with_retry("GET", f"/api/prm/positions/{position_id}/accounts")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_conversion_aggregates() -> list[dict]:
    logger.info("GET /api/conversions/aggregates")
    response = await _request_with_retry("GET", "/api/conversions/aggregates")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_conversion_preview(company: str, price: float, amount: float, include_pdf: bool = False) -> dict:
    # Single attempt, no retry: this is a read-only, idempotent, disposable preview fired on every debounced
    # keystroke in the CONV UI. Retrying through the backoff ladder would stack stale in-flight calls and delay
    # the UI's response by seconds when a newer keystroke has already superseded this one.
    logger.info(
        "GET /api/conversion-notices/preview company=%s price=%s amount=%s includePdf=%s (single attempt)",
        company, price, amount, include_pdf,
    )
    client = _get_client()
    response = await client.get(
        "/api/conversion-notices/preview",
        params={"company": company, "price": price, "amount": amount, "includePdf": str(include_pdf).lower()},
    )
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    if response.status_code >= 400:
        logger.warning("  → DTS preview error (%s): %s", response.status_code, response.text[:500])
    response.raise_for_status()
    return response.json()


async def get_convertible_tranches(symbol: str) -> list[dict]:
    logger.info("GET /api/conversions/convertible-tranches?symbol=%s", symbol)
    response = await _request_with_retry(
        "GET", "/api/conversions/convertible-tranches", params={"symbol": symbol})
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    if response.status_code >= 400:
        logger.warning("  → DTS convertible-tranches error (%s): %s", response.status_code, response.text[:500])
    response.raise_for_status()
    return response.json()


async def get_conversion_recalc_window() -> dict:
    logger.info("GET /api/conversions/recalc-window")
    response = await _request_with_retry("GET", "/api/conversions/recalc-window")
    logger.info("  → %s", response.status_code)
    response.raise_for_status()
    return response.json()


async def get_conversion_notice_classes() -> list[dict]:
    logger.info("GET /api/convertible-notes/notice-classes")
    response = await _request_with_retry("GET", "/api/convertible-notes/notice-classes")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_preferred_notice_classes() -> list[dict]:
    logger.info("GET /api/preferred-conversions/notice-classes")
    response = await _request_with_retry("GET", "/api/preferred-conversions/notice-classes")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_conversion_lock(company: str) -> dict:
    logger.info("GET /api/conversions/lock/%s", company)
    response = await _request_with_retry("GET", f"/api/conversions/lock/{company}")
    response.raise_for_status()
    return response.json()


async def get_conversion_rule144() -> list[dict]:
    logger.info("GET /api/conversions/rule144")
    response = await _request_with_retry("GET", "/api/conversions/rule144")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_execution_status() -> dict:
    response = await _request_with_retry("GET", "/api/execution/status")
    response.raise_for_status()
    return response.json()


async def get_execution_config() -> dict:
    response = await _request_with_retry("GET", "/api/execution/config")
    response.raise_for_status()
    return response.json()


async def update_execution_config(body: dict, reconnect: bool = True) -> dict:
    logger.info("PUT /api/execution/config %s:%s reconnect=%s", body.get("serverAddress"), body.get("serverPort"), reconnect)
    response = await _request_with_retry("PUT", "/api/execution/config", params={"reconnect": str(reconnect).lower()}, json=body)
    response.raise_for_status()
    return response.json()


async def execution_connect() -> dict:
    logger.info("POST /api/execution/connect")
    response = await _request_with_retry("POST", "/api/execution/connect")
    response.raise_for_status()
    return response.json()


async def execution_disconnect() -> dict:
    logger.info("POST /api/execution/disconnect")
    response = await _request_with_retry("POST", "/api/execution/disconnect")
    response.raise_for_status()
    return response.json()


async def get_pt_companies() -> dict:
    response = await _request_with_retry("GET", "/api/pt/companies")
    response.raise_for_status()
    return response.json()


async def set_pt_company_over_the_wall(company_id: int, body: dict) -> dict:
    logger.info("PUT /api/pt/companies/%s/over-the-wall -> %s (single attempt — write)", company_id, body.get("overTheWall"))
    client = _get_client()
    response = await client.put(f"/api/pt/companies/{company_id}/over-the-wall", json=body)
    response.raise_for_status()
    return response.json()


async def set_pt_company_no_short(company_id: int, body: dict) -> dict:
    logger.info("PUT /api/pt/companies/%s/no-short -> %s (single attempt — write)", company_id, body.get("noShort"))
    client = _get_client()
    response = await client.put(f"/api/pt/companies/{company_id}/no-short", json=body)
    response.raise_for_status()
    return response.json()


async def get_pt_allocation_log(company_id: int | None, from_date: str | None, to_date: str | None, limit: int = 1000) -> dict:
    params: dict = {"limit": limit}
    if company_id is not None:
        params["companyId"] = company_id
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    logger.info("GET /api/pt/allocation-log params=%s", params)
    response = await _request_with_retry("GET", "/api/pt/allocation-log", params=params)
    response.raise_for_status()
    return response.json()


async def get_pt_otw_audit(company_id: int | None, from_date: str | None, to_date: str | None, limit: int = 500) -> dict:
    params: dict = {"limit": limit}
    if company_id is not None:
        params["companyId"] = company_id
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    logger.info("GET /api/pt/companies/otw-audit params=%s", params)
    response = await _request_with_retry("GET", "/api/pt/companies/otw-audit", params=params)
    response.raise_for_status()
    return response.json()


async def get_pt_traders(company_id: int | None = None) -> dict:
    params = {"companyId": company_id} if company_id is not None else None
    response = await _request_with_retry("GET", "/api/pt/traders", params=params)
    response.raise_for_status()
    return response.json()


async def get_pt_allocations(trader_id: int) -> dict:
    response = await _request_with_retry("GET", "/api/pt/allocations", params={"traderId": trader_id})
    response.raise_for_status()
    return response.json()


async def get_pt_open_orders(trader_id: int, company_id: int) -> dict:
    response = await _request_with_retry("GET", "/api/pt/open-orders", params={"traderId": trader_id, "companyId": company_id})
    response.raise_for_status()
    return response.json()


async def get_pt_order_log(trader_id: int, symbol: str, period: str | None = None) -> dict:
    params = {"traderId": trader_id, "symbol": symbol}
    if period:
        params["period"] = period
    response = await _request_with_retry("GET", "/api/pt/order-log", params=params)
    response.raise_for_status()
    return response.json()


async def get_pt_non_trading(company_id: int, symbol: str, period: str | None = None) -> dict:
    params = {"companyId": company_id, "symbol": symbol}
    if period:
        params["period"] = period
    response = await _request_with_retry("GET", "/api/pt/non-trading", params=params)
    response.raise_for_status()
    return response.json()


async def get_pt_auto_allocation_metrics() -> dict:
    response = await _request_with_retry("GET", "/api/pt/auto-allocation/metrics")
    response.raise_for_status()
    return response.json()


async def get_pt_auto_allocation(company_id: int) -> dict:
    logger.info("GET /api/pt/auto-allocation companyId=%s", company_id)
    response = await _request_with_retry("GET", "/api/pt/auto-allocation", params={"companyId": company_id})
    response.raise_for_status()
    return response.json()


async def save_pt_auto_allocation(body: dict) -> tuple[int, dict]:
    """Save a company's auto-allocation settings — a write (company upsert + trader delete/insert), so single attempt, no retry."""
    client = _get_client()
    logger.info(
        "POST /api/pt/auto-allocation (single attempt — write) companyId=%s enabled=%s metric=%s traders=%s",
        body.get("companyId"), body.get("enabled"), body.get("allocationMetric"), len(body.get("traders") or []),
    )
    response = await client.post("/api/pt/auto-allocation", json=body)
    logger.info("  → %s", response.status_code)
    try:
        data = response.json()
    except Exception:
        data = {"message": response.text}
    return response.status_code, data


async def post_pt_trader_action(trader_id: int, action: str, body: dict) -> tuple[int, dict]:
    """Block / unblock / cancel-all for a trader — a write (may send live EMSX cancels), so single attempt, no retry."""
    client = _get_client()
    logger.info("POST /api/pt/traders/%s/%s (single attempt — write) by %s", trader_id, action, body.get("userName"))
    response = await client.post(f"/api/pt/traders/{trader_id}/{action}", json=body)
    logger.info("  → %s", response.status_code)
    try:
        data = response.json()
    except Exception:
        data = {"message": response.text}
    return response.status_code, data


async def get_tm_traders() -> dict:
    response = await _request_with_retry("GET", "/api/pt/trader-mgmt/traders")
    response.raise_for_status()
    return response.json()


async def get_tm_brokers() -> dict:
    response = await _request_with_retry("GET", "/api/pt/trader-mgmt/brokers")
    response.raise_for_status()
    return response.json()


async def get_tm_broker_accounts(broker_id: int) -> dict:
    response = await _request_with_retry("GET", f"/api/pt/trader-mgmt/brokers/{broker_id}/accounts")
    response.raise_for_status()
    return response.json()


async def get_tm_trader(trader_id: int) -> dict:
    response = await _request_with_retry("GET", f"/api/pt/trader-mgmt/traders/{trader_id}")
    response.raise_for_status()
    return response.json()


async def create_tm_trader(body: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("POST /api/pt/trader-mgmt/traders name=%s (write)", body.get("name"))
    response = await client.post("/api/pt/trader-mgmt/traders", json=body)
    logger.info("  → %s", response.status_code)
    try:
        return response.status_code, response.json()
    except Exception:
        return response.status_code, {"message": response.text}


async def save_tm_trader(trader_id: int, body: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("PUT /api/pt/trader-mgmt/traders/%s (write)", trader_id)
    response = await client.put(f"/api/pt/trader-mgmt/traders/{trader_id}", json=body)
    logger.info("  → %s", response.status_code)
    try:
        return response.status_code, response.json()
    except Exception:
        return response.status_code, {"message": response.text}


async def delete_tm_trader(trader_id: int) -> tuple[int, dict]:
    client = _get_client()
    logger.info("DELETE /api/pt/trader-mgmt/traders/%s (write)", trader_id)
    response = await client.delete(f"/api/pt/trader-mgmt/traders/{trader_id}")
    logger.info("  → %s", response.status_code)
    try:
        return response.status_code, response.json()
    except Exception:
        return response.status_code, {"message": response.text}


async def get_pt_user_settings(user_key: str) -> dict:
    response = await _request_with_retry("GET", "/api/pt/user-settings", params={"userKey": user_key})
    response.raise_for_status()
    return response.json()


async def set_pt_user_settings(user_key: str, user_name: str | None) -> dict:
    client = _get_client()
    logger.info("PUT /api/pt/user-settings userKey=%s (write)", user_key)
    response = await client.put("/api/pt/user-settings", json={"userKey": user_key, "userName": user_name})
    response.raise_for_status()
    return response.json()


async def cancel_open_order(order_id: str, body: dict) -> tuple[int, dict]:
    """Per-row cancel of a single open order (sends a live EMSX cancel) — write, single attempt."""
    client = _get_client()
    logger.info("POST /api/pt/open-orders/%s/cancel (write) by %s", order_id, body.get("userName"))
    response = await client.post(f"/api/pt/open-orders/{order_id}/cancel", json=body)
    logger.info("  → %s", response.status_code)
    try:
        return response.status_code, response.json()
    except Exception:
        return response.status_code, {"message": response.text}


async def delete_order_log(order_id: str) -> tuple[int, dict]:
    """Per-row delete of an Order Log entry (removes the order's order_audit rows) — write, single attempt."""
    client = _get_client()
    logger.info("DELETE /api/pt/order-log/%s (write)", order_id)
    response = await client.delete(f"/api/pt/order-log/{order_id}")
    logger.info("  → %s", response.status_code)
    try:
        return response.status_code, response.json()
    except Exception:
        return response.status_code, {"message": response.text}


async def delete_non_trading(tx_id: int) -> tuple[int, dict]:
    """Per-row delete of a non-trading transaction — write, single attempt."""
    client = _get_client()
    logger.info("DELETE /api/pt/non-trading/%s (write)", tx_id)
    response = await client.delete(f"/api/pt/non-trading/{tx_id}")
    logger.info("  → %s", response.status_code)
    try:
        return response.status_code, response.json()
    except Exception:
        return response.status_code, {"message": response.text}


async def get_position_brokers(position_id: int, instrument_type: str) -> dict:
    response = await _request_with_retry("GET", f"/api/pt/positions/{position_id}/brokers", params={"instrumentType": instrument_type})
    response.raise_for_status()
    return response.json()


async def get_position_accounts(position_id: int, instrument_type: str, broker_id: int) -> dict:
    response = await _request_with_retry("GET", f"/api/pt/positions/{position_id}/accounts", params={"instrumentType": instrument_type, "brokerId": broker_id})
    response.raise_for_status()
    return response.json()


async def dts_reachable() -> bool:
    """Quick liveness probe of DTS over the existing on-prem connection — backs the portal's DTS nav icon.
    Short timeout, no retry, so 'down' surfaces promptly."""
    try:
        r = await _get_client().get("/health", timeout=5.0)
        return r.status_code < 500
    except Exception as exc:
        logger.warning("DTS health probe failed: %s", exc)
        return False


async def set_conversion_allow144(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("POST /api/conversions/rule144/allow company=%s allow=%s", payload.get("company"), payload.get("allow"))
    response = await client.post("/api/conversions/rule144/allow", json=payload)
    logger.info("  → %s", response.status_code)
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def get_brokers_with_accounts() -> list[dict]:
    response = await _request_with_retry("GET", "/api/brokers/with-accounts")
    response.raise_for_status()
    return response.json()


async def set_note_broker_account(instrument_id: int, body: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("PUT /api/convertible-notes/%s/broker-account broker=%s account=%s (write)", instrument_id, body.get("brokerId"), body.get("accountId"))
    response = await client.put(f"/api/convertible-notes/{instrument_id}/broker-account", json=body)
    logger.info("  → %s", response.status_code)
    try:
        return response.status_code, response.json()
    except Exception:
        return response.status_code, {"message": response.text}


async def set_preferred_broker_account(instrument_id: int, tranche_no: int, body: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("PUT /api/preferred-series/%s/%s/broker-account broker=%s account=%s (write)", instrument_id, tranche_no, body.get("brokerId"), body.get("accountId"))
    response = await client.put(f"/api/preferred-series/{instrument_id}/{tranche_no}/broker-account", json=body)
    logger.info("  → %s", response.status_code)
    try:
        return response.status_code, response.json()
    except Exception:
        return response.status_code, {"message": response.text}


async def set_note_conversion_enabled(instrument_id: int, body: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("PUT /api/convertible-notes/%s/conversion-enabled enabled=%s (write)", instrument_id, body.get("enabled"))
    response = await client.put(f"/api/convertible-notes/{instrument_id}/conversion-enabled", json=body)
    logger.info("  → %s", response.status_code)
    try:
        return response.status_code, response.json()
    except Exception:
        return response.status_code, {"message": response.text}


async def set_preferred_conversion_enabled(instrument_id: int, tranche_no: int, body: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("PUT /api/preferred-series/%s/%s/conversion-enabled enabled=%s (write)", instrument_id, tranche_no, body.get("enabled"))
    response = await client.put(f"/api/preferred-series/{instrument_id}/{tranche_no}/conversion-enabled", json=body)
    logger.info("  → %s", response.status_code)
    try:
        return response.status_code, response.json()
    except Exception:
        return response.status_code, {"message": response.text}


async def set_conversion_acceleration_true_ups(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("POST /api/conversions/acceleration-true-ups/allow company=%s allow=%s", payload.get("company"), payload.get("allow"))
    response = await client.post("/api/conversions/acceleration-true-ups/allow", json=payload)
    logger.info("  → %s", response.status_code)
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def set_conversion_installment_true_ups(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("POST /api/conversions/installment-true-ups/allow company=%s allow=%s", payload.get("company"), payload.get("allow"))
    response = await client.post("/api/conversions/installment-true-ups/allow", json=payload)
    logger.info("  → %s", response.status_code)
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def set_conversion_trading_objective(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("POST /api/conversions/trading-objective company=%s objective=%s", payload.get("company"), payload.get("objective"))
    response = await client.post("/api/conversions/trading-objective", json=payload)
    logger.info("  → %s", response.status_code)
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def acquire_conversion_lock(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("POST /api/conversions/lock company=%s owner=%s", payload.get("company"), payload.get("owner"))
    response = await client.post("/api/conversions/lock", json=payload)
    logger.info("  → %s", response.status_code)
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def release_conversion_lock(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("POST /api/conversions/unlock company=%s owner=%s", payload.get("company"), payload.get("owner"))
    response = await client.post("/api/conversions/unlock", json=payload)
    logger.info("  → %s", response.status_code)
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def convert_basic(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info(
        "POST /api/conversions/convert company=%s price=%s amount=%s owner=%s",
        payload.get("company"), payload.get("price"), payload.get("amount"), payload.get("owner"),
    )
    response = await client.post("/api/conversions/convert", json=payload)
    logger.info("  → %s", response.status_code)
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def get_pre_delivery(instrument_id: int) -> dict:
    logger.info("GET /api/pre-delivery-share/%s", instrument_id)
    response = await _request_with_retry("GET", f"/api/pre-delivery-share/{instrument_id}")
    logger.info("  → %s", response.status_code)
    response.raise_for_status()
    return response.json()


async def set_pre_delivery(instrument_id: int, payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("PUT /api/pre-delivery-share/%s shares=%s", instrument_id, payload.get("shares"))
    response = await client.put(f"/api/pre-delivery-share/{instrument_id}", json=payload)
    logger.info("  → %s", response.status_code)
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def get_conversion_completed(company: str) -> dict:
    logger.info("GET /api/conversions/completed/%s", company)
    response = await _request_with_retry("GET", f"/api/conversions/completed/{company}")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_conversion_pdf(conversion_id: str, notice_index: int, doc_type: str) -> dict:
    logger.info("GET /api/conversions/%s/pdf/%s/%s", conversion_id, notice_index, doc_type)
    response = await _request_with_retry("GET", f"/api/conversions/{conversion_id}/pdf/{notice_index}/{doc_type}")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def delete_conversion(conversion_id: str) -> tuple[int, dict]:
    client = _get_client()
    logger.info("DELETE /api/conversions/%s", conversion_id)
    response = await client.delete(f"/api/conversions/{conversion_id}")
    logger.info("  → %s", response.status_code)
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def remove_conversion(conversion_id: str) -> tuple[int, dict]:
    client = _get_client()
    logger.info("POST /api/conversions/%s/remove", conversion_id)
    response = await client.post(f"/api/conversions/{conversion_id}/remove")
    logger.info("  → %s", response.status_code)
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def get_preferred_companies() -> list[dict]:
    logger.info("GET /api/preferred-conversions/companies")
    response = await _request_with_retry("GET", "/api/preferred-conversions/companies")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_preferred_preview(instrument_id: int, amount: float, conversion_type: str = "Variable") -> dict:
    # Single attempt, no retry: read-only, disposable, fired on every debounced keystroke in the PREF UI.
    logger.info(
        "GET /api/preferred-conversions/preview instrumentId=%s amount=%s type=%s (single attempt)",
        instrument_id, amount, conversion_type,
    )
    client = _get_client()
    response = await client.get(
        "/api/preferred-conversions/preview",
        params={"instrumentId": instrument_id, "amount": amount, "conversionType": conversion_type},
    )
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    if response.status_code >= 400:
        logger.warning("  → DTS preferred preview error (%s): %s", response.status_code, response.text[:500])
    response.raise_for_status()
    return response.json()


async def get_preferred_company_preview(company_id: int, price: float, amount: float) -> dict:
    # Single attempt, no retry: read-only, disposable, fired on every debounced keystroke in the PREF UI.
    logger.info(
        "GET /api/preferred-conversions/company-preview companyId=%s price=%s amount=%s (single attempt)",
        company_id, price, amount,
    )
    client = _get_client()
    response = await client.get(
        "/api/preferred-conversions/company-preview",
        params={"companyId": company_id, "price": price, "amount": amount},
    )
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    if response.status_code >= 400:
        logger.warning("  → DTS preferred company-preview error (%s): %s", response.status_code, response.text[:500])
    response.raise_for_status()
    return response.json()


async def preferred_company_convert(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info(
        "POST /api/preferred-conversions/company-convert companyId=%s price=%s amount=%s owner=%s",
        payload.get("companyId"), payload.get("price"), payload.get("amount"), payload.get("owner"),
    )
    response = await client.post("/api/preferred-conversions/company-convert", json=payload)
    logger.info("  → %s", response.status_code)
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def reverse_preferred_batch(batch_ref: str) -> tuple[int, dict]:
    client = _get_client()
    logger.info("DELETE /api/preferred-conversions/batch/%s", batch_ref)
    response = await client.delete(f"/api/preferred-conversions/batch/{batch_ref}")
    logger.info("  → %s", response.status_code)
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def get_preferred_completed(company_id: int) -> list[dict]:
    logger.info("GET /api/preferred-conversions?companyId=%s", company_id)
    response = await _request_with_retry("GET", "/api/preferred-conversions", params={"companyId": company_id})
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def preferred_convert(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info(
        "POST /api/preferred-conversions instrumentId=%s type=%s amount=%s owner=%s",
        payload.get("instrumentId"), payload.get("conversionType"), payload.get("dollarAmount"), payload.get("owner"),
    )
    response = await client.post("/api/preferred-conversions", json=payload)
    logger.info("  → %s", response.status_code)
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def delete_preferred_conversion(conversion_id: str) -> tuple[int, dict]:
    client = _get_client()
    logger.info("DELETE /api/preferred-conversions/%s", conversion_id)
    response = await client.delete(f"/api/preferred-conversions/{conversion_id}")
    logger.info("  → %s", response.status_code)
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def set_preferred_allow_true_up(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("PUT /api/company-preferred-conversions/allow-true-up company=%s allow=%s",
                payload.get("companyId"), payload.get("allow"))
    response = await client.put("/api/company-preferred-conversions/allow-true-up", json=payload)
    logger.info("  → %s", response.status_code)
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def set_preferred_trading_objective(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("PUT /api/company-preferred-conversions/trading-objective company=%s objective=%s",
                payload.get("companyId"), payload.get("objective"))
    response = await client.put("/api/company-preferred-conversions/trading-objective", json=payload)
    logger.info("  → %s", response.status_code)
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def post_prm_synthetic_trade(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info(
        "POST /api/prm/positions/synthetic-trade %s %s qty=%s (single attempt — write)",
        payload.get("symbol"), "BUY" if payload.get("isBuy") else "SELL", payload.get("quantity"),
    )
    response = await client.post("/api/prm/positions/synthetic-trade", json=payload)
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def post_prm_restricted_trade(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info(
        "POST /api/prm/positions/restricted-trade %s %s qty=%s (single attempt — write)",
        payload.get("symbol"), "ADD" if payload.get("isBuy") else "REMOVE", payload.get("quantity"),
    )
    response = await client.post("/api/prm/positions/restricted-trade", json=payload)
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def post_prm_transfer(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info(
        "POST /api/prm/positions/transfer %s %s qty=%s (single attempt — write)",
        payload.get("symbol"), "R->U" if payload.get("isRestrictedToUnrestricted") else "U->R", payload.get("quantity"),
    )
    response = await client.post("/api/prm/positions/transfer", json=payload)
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def get_prm_preferred_positions(company_id: int) -> list[dict]:
    logger.info("GET /api/prm/positions/preferred?companyId=%s", company_id)
    response = await _request_with_retry("GET", "/api/prm/positions/preferred", params={"companyId": company_id})
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_prm_warrant_positions(company_id: int) -> list[dict]:
    logger.info("GET /api/prm/positions/warrant?companyId=%s", company_id)
    response = await _request_with_retry("GET", "/api/prm/positions/warrant", params={"companyId": company_id})
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_prm_convertible_positions(company_id: int) -> list[dict]:
    logger.info("GET /api/prm/positions/convertible?companyId=%s", company_id)
    response = await _request_with_retry("GET", "/api/prm/positions/convertible", params={"companyId": company_id})
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def post_prm_derivative_trade(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("POST /api/prm/positions/derivative-trade %s %s %s qty=%s (single attempt — write)",
                payload.get("instrumentType"), "BUY" if payload.get("isBuy") else "SELL",
                payload.get("symbol"), payload.get("quantity"))
    response = await client.post("/api/prm/positions/derivative-trade", json=payload)
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def post_prm_create_position(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("POST /api/prm/positions/create type=%s symbol=%s companyId=%s (single attempt — write)",
                payload.get("type"), payload.get("symbol"), payload.get("companyId"))
    response = await client.post("/api/prm/positions/create", json=payload)
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def get_prm_trader_position(trader_id: int, position_id: int, instrument_type: str) -> dict:
    logger.info("GET /api/prm/allocations/trader-position trader=%s position=%s instrument=%s", trader_id, position_id, instrument_type)
    response = await _request_with_retry(
        "GET", "/api/prm/allocations/trader-position",
        params={"traderId": trader_id, "positionId": position_id, "instrumentType": instrument_type})
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def post_prm_allocate(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("POST /api/prm/allocations/allocate trader=%s position=%s amount=%s instrument=%s (single attempt — write)",
                payload.get("traderId"), payload.get("positionId"), payload.get("amount"), payload.get("instrumentType"))
    response = await client.post("/api/prm/allocations/allocate", json=payload)
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def post_prm_deallocate(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("POST /api/prm/allocations/deallocate trader=%s position=%s amount=%s instrument=%s (single attempt — write)",
                payload.get("traderId"), payload.get("positionId"), payload.get("amount"), payload.get("instrumentType"))
    response = await client.post("/api/prm/allocations/deallocate", json=payload)
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def post_prm_deemed_to_own(payload: dict) -> tuple[int, dict]:
    client = _get_client()
    logger.info("POST /api/prm/deemed-to-own source=%s symbol=%s companyId=%s shares=%s (single attempt — write)",
                payload.get("source"), payload.get("companySymbol"), payload.get("companyId"), payload.get("shares"))
    response = await client.post("/api/prm/deemed-to-own", json=payload)
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    try:
        body = response.json()
    except Exception:
        body = {"message": response.text}
    return response.status_code, body


async def get_eloc_state_by_id(eloc_id: str) -> dict | None:
    logger.info("GET /api/eloc/states/%s", eloc_id)
    response = await _request_with_retry("GET", f"/api/eloc/states/{eloc_id}")
    if response.status_code == 404:
        logger.warning("  → 404 not found")
        return None
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def exclude_eloc(eloc_id: str) -> bool:
    logger.info("POST /api/eloc/workflow/%s/exclude", eloc_id)
    response = await _request_with_retry("POST", f"/api/eloc/workflow/{eloc_id}/exclude")
    logger.info("  → %s", response.status_code)
    return response.is_success


async def hide_portal_eloc(eloc_id: str) -> bool:
    logger.info("POST /api/portal/eloc/states/%s/hide", eloc_id)
    response = await _request_with_retry("POST", f"/api/portal/eloc/states/{eloc_id}/hide")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    if response.is_success:
        logger.info("  ELOC %s hidden from client Portal UI", eloc_id)
    else:
        logger.warning("  Hide failed for ELOC %s: %s", eloc_id, response.text[:200])
    return response.is_success


async def exclude_portal_eloc(eloc_id: str) -> bool:
    logger.info("POST /api/portal/eloc/states/%s/exclude", eloc_id)
    response = await _request_with_retry("POST", f"/api/portal/eloc/states/{eloc_id}/exclude")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    if response.is_success:
        logger.info("  Portal ELOC %s excluded (Remove)", eloc_id)
    else:
        logger.warning("  Exclude failed for portal ELOC %s: %s", eloc_id, response.text[:200])
    return response.is_success


async def delete_portal_eloc(eloc_id: str) -> dict | None:
    logger.info("DELETE /api/portal/eloc/states/%s", eloc_id)
    response = await _request_with_retry("DELETE", f"/api/portal/eloc/states/{eloc_id}")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    if not response.is_success:
        logger.warning("  Delete failed for portal ELOC %s: %s", eloc_id, response.text[:200])
        return None
    try:
        body = response.json()
    except ValueError:
        logger.warning("  DTS delete response was not JSON for %s: %s", eloc_id, response.text[:200])
        return None
    logger.info(
        "  Portal ELOC %s deleted — deletedCount=%s, dtoReversed=%s, sharesReversed=%s, commitmentReversed=%s, sharesOutcome=%s, commitmentOutcome=%s",
        eloc_id, body.get("deletedCount"), body.get("dtoReversed"), body.get("sharesReversed"),
        body.get("commitmentReversed"), body.get("sharesOutcome"), body.get("commitmentOutcome"),
    )
    return body


async def get_eloc_data(eloc_id: str) -> dict | None:
    logger.info("GET /api/eloc/data/%s", eloc_id)
    response = await _request_with_retry("GET", f"/api/eloc/data/{eloc_id}")
    if response.status_code == 404:
        logger.warning("  → 404 not found")
        return None
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_all_company_summaries() -> list[dict]:
    logger.info("GET /api/sharesavailable")
    response = await _request_with_retry("GET", "/api/sharesavailable")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()



async def get_shares_available(symbol: str) -> dict:
    logger.info("GET /api/sharesavailable/%s", symbol)
    response = await _request_with_retry("GET", f"/api/sharesavailable/{symbol}")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    logger.debug("  → body: %s", response.text[:2000])
    response.raise_for_status()
    return response.json()


async def get_eloc_available_capital(symbol: str) -> dict:
    logger.info("GET /api/sharesavailable/available-capital/%s", symbol)
    response = await _request_with_retry("GET", f"/api/sharesavailable/available-capital/{symbol}")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_purchase_notice_fields(symbol: str, pricing_period_id: int) -> dict | None:
    logger.info("GET /api/purchasenotice/fields/%s/%s", symbol, pricing_period_id)
    response = await _request_with_retry(
        "GET", f"/api/purchasenotice/fields/{symbol}/{pricing_period_id}")
    if response.status_code == 404:
        logger.warning("  → 404 not found")
        return None
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()



async def get_template_field_catalog(document_type: str) -> list[dict]:
    logger.info("GET /api/template-field-catalog/%s", document_type)
    response = await _request_with_retry("GET", f"/api/template-field-catalog/{document_type}")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def render_participation_pdf_preview(payload: dict) -> tuple[int, bytes, str]:
    logger.info(
        "POST /api/participation-pdf/preview docType=%s fields=%d",
        payload.get("documentType"), len(payload.get("fields") or []),
    )
    response = await _request_with_retry("POST", "/api/participation-pdf/preview", json=payload)
    content_type = response.headers.get("content-type", "application/pdf")
    logger.info("  → %s (%d bytes, %s)", response.status_code, len(response.content), content_type)
    return response.status_code, response.content, content_type



class ElocAlreadyPricingError(Exception):
    """
    Raised when DTS rejects a portal purchase notice submission because the
    company already has an active ELOC. Carries the structured body DTS
    returned (companyId, blockingElocId, blockingWorkflowStep) so the FastAPI
    router can surface a friendly 409 to the frontend.
    """
    def __init__(self, body: dict):
        self.body = body or {}
        self.code = self.body.get("code", "ELOC_ALREADY_PRICING")
        self.blocking_eloc_id = self.body.get("blockingElocId")
        self.blocking_workflow_step = self.body.get("blockingWorkflowStep")
        self.company_id = self.body.get("companyId")
        msg = self.body.get("error") or "An ELOC for this company is already in progress."
        super().__init__(msg)


async def submit_portal_purchase_notice(payload: dict) -> dict:
    logger.info(
        "POST /api/portal/purchase-notice symbol=%s period=%s shares=%s company=%s",
        payload.get("symbol"), payload.get("pricing_period_id"),
        payload.get("shares"), payload.get("company_id"),
    )
    safe_payload = {
        k: (v[:80] + "..." if isinstance(v, str) and len(v) > 80 else v)
        for k, v in payload.items()
    }
    logger.info("  payload keys: %s", list(payload.keys()))
    logger.debug("  payload: %s", safe_payload)

    response = await _request_with_retry("POST", "/api/portal/purchase-notice", json=payload)
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))

    if response.status_code == 409:
        try:
            body = response.json()
        except Exception:
            body = {}
        if body.get("code") == "ELOC_ALREADY_PRICING":
            logger.warning(
                "  → DTS rejected submission: ELOC_ALREADY_PRICING — "
                "company=%s blockingEloc=%s blockingStep=%s",
                body.get("companyId"),
                body.get("blockingElocId"),
                body.get("blockingWorkflowStep"),
            )
            raise ElocAlreadyPricingError(body)
        logger.error("  → 409 with unrecognized body: %s", response.text[:2000])

    if response.status_code >= 400:
        logger.error("  → DTS error response: %s", response.text[:2000])
    else:
        logger.debug("  → body: %s", response.text[:2000])
    response.raise_for_status()
    return response.json()


async def get_portal_eloc_states_included() -> list[dict]:
    logger.info("GET /api/portal/eloc/states/included")
    response = await _request_with_retry("GET", "/api/portal/eloc/states/included")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_portal_eloc_state_by_id(eloc_id: str) -> dict | None:
    logger.info("GET /api/portal/eloc/states/%s", eloc_id)
    response = await _request_with_retry("GET", f"/api/portal/eloc/states/{eloc_id}")
    if response.status_code == 404:
        logger.warning("  → 404 not found")
        return None
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_document_recipients(eloc_id: str) -> dict | None:
    import time
    t_start = time.monotonic()
    logger.info("GET /api/portal/eloc/%s/document-recipients", eloc_id)
    response = await _request_with_retry(
        "GET", f"/api/portal/eloc/{eloc_id}/document-recipients")
    if response.status_code == 404:
        elapsed_ms = (time.monotonic() - t_start) * 1000
        logger.warning("  → 404 not found (%.1fms)", elapsed_ms)
        return None
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    try:
        data = response.json()
    except Exception as parse_exc:
        elapsed_ms = (time.monotonic() - t_start) * 1000
        logger.error(
            "  recipients(%s): JSON parse FAILED after %.1fms — body[:500]=%r",
            eloc_id, elapsed_ms, response.text[:500],
        )
        raise
    elapsed_ms = (time.monotonic() - t_start) * 1000

    outcomes = data.get("outcomes", {})
    firm_sig = data.get("firm_signature") or {}
    firm_sig_src = data.get("firm_signature_source") or {}
    sig_img = firm_sig.get("signature_image_base64") or ""
    logger.info(
        "  recipients(%s) in %.1fms: to_name=%r [%s], to_email=%r [%s] (of %s total), "
        "firm.email=%r [%s], firm.name=%r [%s], firm.image=%s "
        "(outcomes: firm_signature=%s, to_name=%s, recipient_email=%s)",
        eloc_id, elapsed_ms,
        data.get("to_name"), data.get("to_name_source"),
        data.get("to_email"), data.get("to_email_source"),
        data.get("to_email_count"),
        firm_sig.get("email"), firm_sig_src.get("email"),
        firm_sig.get("name"), firm_sig_src.get("name"),
        f"{len(sig_img):,} chars base64" if sig_img else "(empty)",
        outcomes.get("firm_signature"),
        outcomes.get("to_name"),
        outcomes.get("recipient_email"),
    )
    return data


async def get_portal_eloc_document(eloc_id: str, step: str) -> dict | None:
    logger.info("GET /api/portal/eloc/documents/%s/%s", eloc_id, step)
    response = await _request_with_retry(
        "GET", f"/api/portal/eloc/documents/{eloc_id}/{step}")
    if response.status_code == 404:
        logger.warning("  → 404 not found")
        return None
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_pricing_details_pdf(eloc_id: str) -> bytes | None:
    # The ELOC Pricing Details PDF is rendered on-demand by DTS from eloc_data.pricing_breakdown (not a stored doc).
    # Returns the raw PDF bytes, or None when the ELOC has no captured breakdown (DTS 400/404).
    logger.info("GET /api/portal/eloc/%s/pricing-details-pdf", eloc_id)
    response = await _request_with_retry("GET", f"/api/portal/eloc/{eloc_id}/pricing-details-pdf")
    if response.status_code in (400, 404):
        logger.info("  → %s (no pricing details for %s)", response.status_code, eloc_id)
        return None
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.content


async def accept_portal_eloc(eloc_id: str) -> dict:
    logger.info("POST /api/portal/eloc/%s/accept", eloc_id)
    response = await _request_with_retry("POST", f"/api/portal/eloc/{eloc_id}/accept")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    if response.status_code >= 400:
        logger.error("  → DTS error response: %s", response.text[:2000])
    else:
        logger.debug("  → body: %s", response.text[:2000])
    response.raise_for_status()
    return response.json()


async def reject_portal_eloc(eloc_id: str) -> dict:
    logger.info("POST /api/portal/eloc/%s/reject", eloc_id)
    response = await _request_with_retry("POST", f"/api/portal/eloc/{eloc_id}/reject")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    if response.status_code >= 400:
        logger.error("  → DTS error response: %s", response.text[:2000])
    else:
        logger.debug("  → body: %s", response.text[:2000])
    response.raise_for_status()
    return response.json()


async def send_portal_eloc_nudge(eloc_id: str) -> dict:
    """Re-send the 'countersign the Purchase Confirmation' action-item nudge email to the company.
    A write (sends an email), so single attempt with no retry — a 5xx retry could double-send."""
    client = _get_client()
    logger.info("POST /api/portal/eloc/%s/send-action-item-nudge (single attempt — sends email)", eloc_id)
    response = await client.post(f"/api/portal/eloc/{eloc_id}/send-action-item-nudge")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    if response.status_code >= 400:
        logger.error("  → DTS error response: %s", response.text[:2000])
    response.raise_for_status()
    return response.json()


# ── Action items (operator error alerts) ──

async def get_action_items() -> list[dict]:
    logger.info("GET /api/action-items")
    response = await _request_with_retry("GET", "/api/action-items")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_action_items_count() -> dict:
    response = await _request_with_retry("GET", "/api/action-items/count")
    response.raise_for_status()
    return response.json()


async def remove_action_item(item_id: int) -> tuple[int, dict]:
    """Remove (soft-resolve) an action item — a write, single attempt (no retry)."""
    client = _get_client()
    logger.info("DELETE /api/action-items/%s (single attempt)", item_id)
    response = await client.delete(f"/api/action-items/{item_id}")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    body = response.json() if response.content else {}
    return response.status_code, body


async def retry_action_item(item_id: int) -> tuple[int, dict]:
    """Retry an action item's workflow step (e.g. re-fire a conversion's email) — a write, single attempt."""
    client = _get_client()
    logger.info("POST /api/action-items/%s/retry (single attempt)", item_id)
    response = await client.post(f"/api/action-items/{item_id}/retry")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    body = response.json() if response.content else {}
    return response.status_code, body

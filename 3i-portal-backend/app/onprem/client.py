"""
3i Fund Portal — DealTermsServer Client
All communication with the on-premises DealTermsServer goes through here.
Includes retry with exponential backoff for transient failures.
"""

import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger("portal.onprem")
_client: httpx.AsyncClient | None = None

# Retry settings
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 2  # seconds
MAX_RETRY_DELAY = 15  # seconds


def _get_client() -> httpx.AsyncClient:
    """Lazily create a shared async HTTP client."""
    global _client
    if _client is None or _client.is_closed:
        logger.info("Creating on-prem HTTP client → %s (timeout=%ss)", settings.onprem_base_url, settings.onprem_timeout_seconds)
        _client = httpx.AsyncClient(
            base_url=settings.onprem_base_url,
            timeout=settings.onprem_timeout_seconds,
        )
    return _client


async def _request_with_retry(method: str, url: str, **kwargs) -> httpx.Response:
    """
    Make an HTTP request with retry and exponential backoff.
    Retries on connection errors, timeouts, and 5xx responses.
    """
    client = _get_client()
    delay = INITIAL_RETRY_DELAY

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code >= 500 and attempt < MAX_RETRIES:
                logger.warning(
                    "  → %s %s returned %s (attempt %d/%d, retry in %ds)",
                    method, url, response.status_code, attempt, MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, MAX_RETRY_DELAY)
                continue
            return response
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, OSError) as exc:
            if attempt == MAX_RETRIES:
                logger.error(
                    "  → %s %s failed after %d attempts: %s",
                    method, url, MAX_RETRIES, exc,
                )
                raise
            logger.warning(
                "  → %s %s failed (attempt %d/%d): %s (retry in %ds)",
                method, url, attempt, MAX_RETRIES, exc, delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, MAX_RETRY_DELAY)

    # Should not reach here, but just in case
    raise httpx.ConnectError(f"Failed after {MAX_RETRIES} attempts")


# ---- Workflow State Endpoints ----

async def get_included_eloc_states() -> list[dict]:
    """
    GET /api/eloc/states/included — all active ELOC workflow states.
    """
    logger.info("GET /api/eloc/states/included")
    response = await _request_with_retry("GET", "/api/eloc/states/included")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_eloc_state_by_id(eloc_id: str) -> dict | None:
    """
    GET /api/eloc/states/{elocId} — single ELOC workflow state.
    """
    logger.info("GET /api/eloc/states/%s", eloc_id)
    response = await _request_with_retry("GET", f"/api/eloc/states/{eloc_id}")
    if response.status_code == 404:
        logger.warning("  → 404 not found")
        return None
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def exclude_eloc(eloc_id: str) -> bool:
    """
    POST /api/eloc/workflow/{elocId}/exclude — exclude ELOC from workflow.
    """
    logger.info("POST /api/eloc/workflow/%s/exclude", eloc_id)
    response = await _request_with_retry("POST", f"/api/eloc/workflow/{eloc_id}/exclude")
    logger.info("  → %s", response.status_code)
    return response.is_success


async def get_all_eloc_states() -> list[dict]:
    """
    GET /api/eloc/states — all ELOC workflow states (admin view).
    """
    logger.info("GET /api/eloc/states")
    response = await _request_with_retry("GET", "/api/eloc/states")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_eloc_data(eloc_id: str) -> dict | None:
    """
    GET /api/eloc/data/{elocId} — full ELOC data (extracted fields, documents, timestamps).
    """
    logger.info("GET /api/eloc/data/%s", eloc_id)
    response = await _request_with_retry("GET", f"/api/eloc/data/{eloc_id}")
    if response.status_code == 404:
        logger.warning("  → 404 not found")
        return None
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_all_company_summaries() -> list[dict]:
    """
    GET /api/sharesavailable — all companies with active ELOC status.
    Returns list of {symbol, companyName, hasActiveEloc}.
    """
    logger.info("GET /api/sharesavailable")
    response = await _request_with_retry("GET", "/api/sharesavailable")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


# ---- Pricing & Shares Endpoints ----

async def get_shares_available(symbol: str) -> dict:
    """
    Fetch available shares calculation from the on-prem C# server.
    Returns all pricing periods for the company's active ELOC.
    """
    logger.info("GET /api/sharesavailable/%s", symbol)
    response = await _request_with_retry("GET", f"/api/sharesavailable/{symbol}")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    logger.debug("  → body: %s", response.text[:2000])
    response.raise_for_status()
    return response.json()


async def get_purchase_notice_fields(symbol: str, pricing_period_id: int) -> dict | None:
    """
    GET /api/purchasenotice/fields/{symbol}/{pricingPeriodId}
    Returns calculated fields for rendering a purchase notice.
    """
    logger.info("GET /api/purchasenotice/fields/%s/%s", symbol, pricing_period_id)
    response = await _request_with_retry(
        "GET", f"/api/purchasenotice/fields/{symbol}/{pricing_period_id}")
    if response.status_code == 404:
        logger.warning("  → 404 not found")
        return None
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def submit_purchase_notice(
    eloc_id: str,
    company_id: str,
    pricing_period: str,
    shares: int,
) -> dict:
    """
    Submit a purchase notice to the on-prem server.
    Returns acknowledgment response.
    """
    logger.info(
        "POST /api/elocs/%s/purchase-notice company_id=%s period=%s shares=%d",
        eloc_id, company_id, pricing_period, shares,
    )
    client = _get_client()
    response = await client.post(
        f"/api/elocs/{eloc_id}/purchase-notice",
        json={
            "company_id": company_id,
            "pricing_period": pricing_period,
            "shares": shares,
        },
    )
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    logger.debug("  → body: %s", response.text[:2000])
    response.raise_for_status()
    return response.json()

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


async def warm_client():
    """Pre-create the HTTP client and test connectivity to DTS.
    Called during app startup to avoid cold-start latency on first user request."""
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
    """
    Make an HTTP request with retry and exponential backoff.
    Retries on connection errors, timeouts, and 5xx responses.
    """
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


async def hide_portal_eloc(eloc_id: str) -> bool:
    """
    POST /api/portal/eloc/states/{elocId}/hide — hide ELOC from client Portal UI.
    Sets workflow_visible=false in MongoDB. Cosmetic only — workflow continues.
    """
    logger.info("POST /api/portal/eloc/states/%s/hide", eloc_id)
    response = await _request_with_retry("POST", f"/api/portal/eloc/states/{eloc_id}/hide")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    if response.is_success:
        logger.info("  ELOC %s hidden from client Portal UI", eloc_id)
    else:
        logger.warning("  Hide failed for ELOC %s: %s", eloc_id, response.text[:200])
    return response.is_success


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


# ---- Portal-Initiated Purchase Notice Endpoints ----

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
    """
    POST /api/portal/purchase-notice — submit portal-initiated purchase notice.
    DTS generates eloc_id, PDF, and writes to three_i_fund_portal MongoDB.

    Raises ElocAlreadyPricingError on HTTP 409 with code=ELOC_ALREADY_PRICING
    so the caller can render the proper "already pricing" UI without treating
    it as a server error.
    """
    logger.info(
        "POST /api/portal/purchase-notice symbol=%s period=%s shares=%s company=%s",
        payload.get("symbol"), payload.get("pricing_period_id"),
        payload.get("shares"), payload.get("company_id"),
    )
    # Log all payload keys and values (excluding large fields like signature images)
    safe_payload = {
        k: (v[:80] + "..." if isinstance(v, str) and len(v) > 80 else v)
        for k, v in payload.items()
    }
    logger.info("  payload keys: %s", list(payload.keys()))
    logger.debug("  payload: %s", safe_payload)

    response = await _request_with_retry("POST", "/api/portal/purchase-notice", json=payload)
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))

    # Concurrency-rejection path: DTS returns 409 with a structured body when
    # the company already has an active ELOC (enforced by the unique partial
    # index on eloc_status_tracker (company_id) WHERE current_status IN
    # ('Pending','InProgress')). Surface this as a typed exception so the
    # FastAPI router translates it to a clean 409 for the frontend rather
    # than the generic 500 path used by other DTS errors.
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
    """
    GET /api/portal/eloc/states/included — all active portal ELOC workflow states.
    """
    logger.info("GET /api/portal/eloc/states/included")
    response = await _request_with_retry("GET", "/api/portal/eloc/states/included")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_portal_eloc_state_by_id(eloc_id: str) -> dict | None:
    """
    GET /api/portal/eloc/states/{elocId} — single portal ELOC workflow state.
    """
    logger.info("GET /api/portal/eloc/states/%s", eloc_id)
    response = await _request_with_retry("GET", f"/api/portal/eloc/states/{eloc_id}")
    if response.status_code == 404:
        logger.warning("  → 404 not found")
        return None
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def get_portal_eloc_document(eloc_id: str, step: str) -> dict | None:
    """
    GET /api/portal/eloc/documents/{elocId}/{step} — document for a portal ELOC step.
    """
    logger.info("GET /api/portal/eloc/documents/%s/%s", eloc_id, step)
    response = await _request_with_retry(
        "GET", f"/api/portal/eloc/documents/{eloc_id}/{step}")
    if response.status_code == 404:
        logger.warning("  → 404 not found")
        return None
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    response.raise_for_status()
    return response.json()


async def accept_portal_eloc(eloc_id: str) -> dict:
    """
    POST /api/portal/eloc/{elocId}/accept — accept current workflow step.
    DTS advances to the next step in the portal sequence.
    """
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
    """
    POST /api/portal/eloc/{elocId}/reject — reject portal ELOC.
    DTS sets status=Rejected, include=false, and removes from tracker.
    """
    logger.info("POST /api/portal/eloc/%s/reject", eloc_id)
    response = await _request_with_retry("POST", f"/api/portal/eloc/{eloc_id}/reject")
    logger.info("  → %s (%d bytes)", response.status_code, len(response.content))
    if response.status_code >= 400:
        logger.error("  → DTS error response: %s", response.text[:2000])
    else:
        logger.debug("  → body: %s", response.text[:2000])
    response.raise_for_status()
    return response.json()

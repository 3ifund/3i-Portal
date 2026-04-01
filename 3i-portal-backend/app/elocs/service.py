"""
3i Fund Portal — ELOC Service Layer
Orchestrates data from DealTermsServer REST API (workflow state, pricing,
shares available, purchase notices).
"""

import logging

from app.onprem import client as onprem

logger = logging.getLogger("portal.elocs.service")


# ---- Step-to-field mapping for ElocData (DealTermsServer camelCase JSON) ----
_STEP_EVENT_MAP = {
    "SignedContractToCompany": {
        "timestamp_field": "receivedAt",
        "document_field": "purchaseNoticeBytes",
    },
    "FinalVwapPricingCalculated": {
        "timestamp_field": "contractualTermsValidatedAt",
        "document_field": None,
    },
    "VwapNotificationToCompany": {
        "timestamp_field": "purchaseConfirmationSentAt",
        "document_field": "purchaseConfirmationBytes",
    },
    "ReceivedCountersignedVwapNotification": {
        "timestamp_field": "countersignedPurchaseConfirmationReceivedAt",
        "document_field": "countersignedPurchaseConfirmationBytes",
    },
}


async def get_company_elocs(
    company_id: int,
    company_symbol: str,
    status_filter: str | None = None,
) -> list[dict]:
    """
    Build ELOC listing from DealTermsServer shares-available data.
    Active ELOCs are determined by whether the company has an active deal
    with pricing periods in the DealTerms PostgreSQL database (via DTS).
    """
    logger.info("Fetching ELOCs for company_id=%s symbol=%s filter=%s",
                company_id, company_symbol, status_filter)

    # No historical data available without direct DB access
    if status_filter == "history":
        logger.info("  History filter — returning empty (no direct DB)")
        return []

    # Get active ELOC data from DealTermsServer shares-available endpoint
    try:
        shares_data = await onprem.get_shares_available(company_symbol)
    except Exception as exc:
        logger.warning("  Shares-available failed for %s: %s", company_symbol, exc)
        return []

    if not shares_data or not shares_data.get("pricingPeriods"):
        logger.info("  No active ELOC deal for %s", company_symbol)
        return []

    period_types = [p.get("periodType", "") for p in shares_data["pricingPeriods"]]
    company_name = shares_data.get("companyName", "")

    # Build a single ELOC entry from the shares-available data
    eloc = {
        "eloc_id": f"{company_symbol}-active",
        "company_id": company_id,
        "company_symbol": company_symbol,
        "company_name": company_name,
        "total_commitment": 0,
        "total_commitment_remaining": 0,
        "registered_shares_available": 0,
        "expiration_date": None,
        "status": "active",
        "pricing_period_types": period_types,
        "pricing_periods_count": len(period_types),
    }

    logger.info("  Returning 1 active ELOC with %d pricing periods", len(period_types))
    return [eloc]


async def get_eloc_detail(eloc_id: int, company_id: int, company_symbol: str = "") -> dict:
    """
    Fetch ELOC detail from DealTermsServer.
    Note: this endpoint is not currently called by the frontend.
    """
    logger.info("Fetching ELOC detail eloc_id=%s company_id=%s", eloc_id, company_id)

    state = await onprem.get_eloc_state_by_id(str(eloc_id))
    if not state:
        logger.warning("  ELOC %s not found in DealTermsServer", eloc_id)
        return {}

    # Get pricing period info from shares-available
    pricing_periods = []
    company_name = ""
    if company_symbol:
        try:
            shares_data = await onprem.get_shares_available(company_symbol)
            company_name = shares_data.get("companyName", "")
            for p in shares_data.get("pricingPeriods", []):
                pricing_periods.append({
                    "pricing_period_id": p.get("pricingPeriodId", 0),
                    "period_type": p.get("periodType", ""),
                    "dollar_cap_per_notice": float(p.get("dollarCapPerNotice", 0)),
                    "discount_multiplier": 0,
                    "volume_pct_cap": None,
                    "acceptance_window_start": p.get("acceptanceWindowStart"),
                    "acceptance_window_end": p.get("acceptanceWindowEnd"),
                    "use_half_days": False,
                })
        except Exception as exc:
            logger.warning("  Shares-available failed: %s", exc)

    return {
        "eloc_id": eloc_id,
        "company_id": company_id,
        "company_symbol": company_symbol,
        "company_name": company_name,
        "total_commitment": 0,
        "total_commitment_used": 0,
        "total_commitment_remaining": 0,
        "registered_shares": 0,
        "registered_shares_used": 0,
        "registered_shares_available": 0,
        "expiration_date": None,
        "min_trading_days_between_notices": 1,
        "threshold_price": None,
        "beneficial_ownership_limit_pct": None,
        "current_shares_outstanding": None,
        "status": "active",
        "pricing_periods": pricing_periods,
    }


async def get_eloc_workflow(eloc_id: str) -> dict:
    """
    Fetch workflow state from DealTermsServer and map to step statuses and events.
    Note: this endpoint is not currently called by the frontend.
    """
    from app.elocs.models import build_workflow_steps

    logger.info("Fetching workflow for eloc_id=%s", eloc_id)

    # Get workflow state
    state = await onprem.get_eloc_state_by_id(eloc_id)
    if not state:
        return {"eloc_id": eloc_id, "steps": {}, "events": {}}

    workflow_step = state.get("workflowStep", "")
    status = state.get("status", "Pending")

    # Build steps dict from current step + status
    step_list, _ = build_workflow_steps(workflow_step, status)
    steps = {s["key"]: s["status"] for s in step_list}
    logger.debug("  Workflow steps: %s", steps)

    # Get event data from DealTermsServer
    events = {}
    data = await onprem.get_eloc_data(eloc_id)
    if data:
        for step_key, mapping in _STEP_EVENT_MAP.items():
            ts = data.get(mapping["timestamp_field"])
            doc_field = mapping["document_field"]
            has_doc = bool(data.get(doc_field)) if doc_field else False
            if ts or has_doc:
                events[step_key] = {
                    "event_datetime": ts,
                    "has_document": has_doc,
                }

    logger.debug("  Events: %s", list(events.keys()))
    return {
        "eloc_id": eloc_id,
        "steps": steps,
        "events": events,
    }


async def get_eloc_document(eloc_id: str, step: str) -> dict | None:
    """
    Fetch document data for a specific workflow step from DealTermsServer.
    Note: this endpoint is not currently called by the frontend.
    """
    logger.info("Fetching document eloc_id=%s step=%s", eloc_id, step)

    data = await onprem.get_eloc_data(eloc_id)
    if not data:
        logger.warning("  No data found for eloc_id=%s", eloc_id)
        return None

    mapping = _STEP_EVENT_MAP.get(step)
    if not mapping:
        logger.warning("  Unknown step=%s", step)
        return None

    doc_field = mapping["document_field"]
    ts_field = mapping["timestamp_field"]

    has_doc = bool(data.get(doc_field)) if doc_field else False
    if not has_doc:
        logger.warning("  Document not found for step=%s", step)
        return None

    result = {
        "step": step,
        "has_document": True,
        "event_datetime": data.get(ts_field),
    }
    logger.info("  Document found")
    return result


async def get_shares_available(company_symbol: str) -> dict:
    """
    Fetch available shares for all pricing periods from DealTermsServer.
    """
    logger.info("get_shares_available symbol=%s", company_symbol)
    result = await onprem.get_shares_available(company_symbol)
    logger.info("  Returned: hasPendingEloc=%s, pricingPeriods=%d, currentQuote=%s",
                result.get("hasPendingEloc"),
                len(result.get("pricingPeriods", [])),
                "present" if result.get("currentQuote") else "absent")
    return result


async def get_action_items(company_id: int) -> list[dict]:
    """
    Fetch pending action items for the company.
    Queries portal_3i.eloc_state for ELOCs at VwapNotificationToCompany/Pending
    that need company countersigning.
    """
    logger.info("get_action_items company_id=%s", company_id)
    items = []

    try:
        from app.database.mongo import get_db, is_connected
        if not is_connected():
            logger.info("  MongoDB not connected — returning empty action items")
            return items

        db = get_db()

        # Query for ELOCs at VwapNotificationToCompany/Pending for this company
        cursor = db.eloc_state.find({
            "company_id": company_id,
            "workflow_step": "VwapNotificationToCompany",
            "status": "Pending",
            "include": True,
        })
        pending_states = await cursor.to_list(length=100)
        logger.info("  Found %d pending VwapNotificationToCompany states", len(pending_states))

        for state in pending_states:
            eloc_id = state.get("eloc_id", "")
            # Look up eloc_data for symbol and pricing info
            eloc_data = await db.eloc_data.find_one({"eloc_id": eloc_id})
            symbol = eloc_data.get("symbol", "") if eloc_data else ""
            shares = eloc_data.get("shares", 0) if eloc_data else 0
            vwap_price = eloc_data.get("vwap_purchase_price") if eloc_data else None
            created_at = state.get("modified_at") or state.get("created_at")

            items.append({
                "type": "countersign_purchase_confirmation",
                "label": "Countersign Purchase Confirmation",
                "eloc_id": eloc_id,
                "symbol": symbol,
                "shares": shares,
                "vwap_price": vwap_price,
                "created_at": created_at.isoformat() if created_at else None,
            })

    except Exception as e:
        logger.error("  Error fetching action items: %s", e)

    logger.info("  Returning %d action items", len(items))
    return items


async def get_pricing_workflows(company_id: int) -> list[dict]:
    """
    Fetch ELOC workflow states from DealTermsServer where include=true.
    Includes both DTS upstream and portal-initiated workflows.
    Filters by company_id and returns derived step statuses for dashboard display.
    """
    from app.elocs.models import build_workflow_steps

    logger.info("get_pricing_workflows company_id=%s", company_id)
    workflows = []

    # Portal-initiated workflows only — 12-step ELOCs are shown in PRM, not here.
    # Cross-workflow blocking is handled by eloc_status_tracker in PostgreSQL
    # (the "ELOC Currently Pricing" message on the shares available cards).
    try:
        portal_states = await onprem.get_portal_eloc_states_included()
        for state in portal_states:
            if state.get("companyId") != company_id:
                continue

            workflow_step = state.get("workflowStep", "")
            status = state.get("status", "Pending")
            steps, can_remove = build_workflow_steps(workflow_step, status)

            workflows.append({
                "eloc_id": str(state.get("elocId", "")),
                "company_id": state.get("companyId"),
                "current_step": workflow_step,
                "step_status": status,
                "updated_at": str(state["modifiedAt"]) if state.get("modifiedAt") else None,
                "can_remove": can_remove,
                "steps": steps,
                "source": "portal",
            })
    except Exception as exc:
        logger.warning("  Failed to fetch portal workflows: %s", exc)

    logger.info("  Returning %d pricing workflows", len(workflows))
    return workflows


async def remove_pricing_workflow(eloc_id: str, company_id: int) -> bool:
    """
    Exclude an ELOC from the workflow via DealTermsServer.
    DealTermsServer handles the removal logic and validation.
    """
    logger.info("remove_pricing_workflow eloc_id=%s company_id=%s", eloc_id, company_id)
    success = await onprem.exclude_eloc(eloc_id)
    if success:
        logger.info("  Excluded eloc_id=%s", eloc_id)
    else:
        logger.warning("  Exclude failed for eloc_id=%s", eloc_id)
    return success


async def submit_purchase_notice(
    eloc_id: str,
    company_id: str,
    pricing_period: str,
    shares: int,
) -> dict:
    """
    Forward purchase notice to on-prem server and return acknowledgment.
    """
    logger.info("submit_purchase_notice eloc=%s company=%s period=%s shares=%d",
                eloc_id, company_id, pricing_period, shares)
    result = await onprem.submit_purchase_notice(eloc_id, company_id, pricing_period, shares)
    logger.info("  On-prem result: %s", result)
    return result

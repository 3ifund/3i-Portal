
import logging

from app.database import postgres as pg
from app.onprem import client as onprem

logger = logging.getLogger("portal.elocs.service")


async def _fetch_scheduled_calculation_times(eloc_ids: list[str]) -> dict[str, str]:
    if not eloc_ids:
        return {}

    pool = pg.get_pool()
    rows = await pool.fetch(
        """
        SELECT eloc_id, scheduled_calculation_time
        FROM eloc_status_tracker
        WHERE eloc_id = ANY($1::text[])
          AND scheduled_calculation_time IS NOT NULL
        """,
        eloc_ids,
    )

    result = {r["eloc_id"]: r["scheduled_calculation_time"].isoformat() for r in rows}
    logger.debug(
        "  fetched scheduled_calculation_time for %d/%d ELOCs: %s",
        len(result), len(eloc_ids), result,
    )
    return result


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
    logger.info("Fetching ELOCs for company_id=%s symbol=%s filter=%s",
                company_id, company_symbol, status_filter)

    if status_filter == "history":
        logger.info("  History filter — returning empty (no direct DB)")
        return []

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
    logger.info("Fetching ELOC detail eloc_id=%s company_id=%s", eloc_id, company_id)

    state = await onprem.get_eloc_state_by_id(str(eloc_id))
    if not state:
        logger.warning("  ELOC %s not found in DealTermsServer", eloc_id)
        return {}

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
    from app.elocs.models import build_workflow_steps

    logger.info("Fetching workflow for eloc_id=%s", eloc_id)

    state = await onprem.get_eloc_state_by_id(eloc_id)
    if not state:
        return {"eloc_id": eloc_id, "steps": {}, "events": {}}

    workflow_step = state.get("workflowStep", "")
    status = state.get("status", "Pending")

    step_list, _ = build_workflow_steps(workflow_step, status)
    steps = {s["key"]: s["status"] for s in step_list}
    logger.debug("  Workflow steps: %s", steps)

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
    logger.info("get_shares_available symbol=%s", company_symbol)
    result = await onprem.get_shares_available(company_symbol)
    logger.info("  Returned: hasPendingEloc=%s, pricingPeriods=%d, currentQuote=%s",
                result.get("hasPendingEloc"),
                len(result.get("pricingPeriods", [])),
                "present" if result.get("currentQuote") else "absent")
    return result


async def get_available_capital(company_symbol: str) -> dict:
    logger.info("get_available_capital symbol=%s", company_symbol)
    result = await onprem.get_eloc_available_capital(company_symbol)
    logger.info("  Returned: symbol=%s, periods=%d",
                result.get("symbol"), len(result.get("periods", [])))
    return result


async def get_action_items(company_id: int) -> list[dict]:
    logger.info("get_action_items company_id=%s", company_id)
    items = []

    try:
        from app.database.mongo import get_db, is_connected
        if not is_connected():
            logger.info("  MongoDB not connected — returning empty action items")
            return items

        db = get_db()

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
                "pricing_breakdown": eloc_data.get("pricing_breakdown") if eloc_data else None,
                "created_at": created_at.isoformat() if created_at else None,
            })

    except Exception as e:
        logger.error("  Error fetching action items: %s", e)

    logger.info("  Returning %d action items", len(items))
    return items


async def get_pricing_workflows(company_id: int) -> list[dict]:
    from app.elocs.models import build_workflow_steps

    logger.info("get_pricing_workflows company_id=%s", company_id)
    workflows = []

    try:
        portal_states = await onprem.get_portal_eloc_states_included()

        company_eloc_ids = [
            str(s.get("elocId", ""))
            for s in portal_states
            if s.get("companyId") == company_id and s.get("workflowVisible") is not False
        ]
        scheduled_by_eloc = await _fetch_scheduled_calculation_times(company_eloc_ids)

        for state in portal_states:
            if state.get("companyId") != company_id:
                continue

            if state.get("workflowVisible") is False:
                logger.debug("  Skipping hidden ELOC %s (workflow_visible=false)", state.get("elocId"))
                continue

            eloc_id = str(state.get("elocId", ""))
            workflow_step = state.get("workflowStep", "")
            status = state.get("status", "Pending")
            pricing_direction = state.get("pricingDirection", "Forward")
            workflow_complete = state.get("workflowComplete", False)
            steps, can_remove = build_workflow_steps(
                workflow_step, status, pricing_direction, workflow_complete)

            scheduled_iso = scheduled_by_eloc.get(eloc_id)
            if scheduled_iso:
                for step in steps:
                    if step.get("key") == "FinalVwapPricingCalculated":
                        step["scheduled_at"] = scheduled_iso
                        logger.info(
                            "  ELOC %s: stamped scheduled_at=%s on FinalVwapPricingCalculated step (ET)",
                            eloc_id, scheduled_iso,
                        )
                        break

            logger.info(
                "  ELOC %s: step=%s, status=%s, direction=%s, complete=%s, can_remove=%s, scheduled=%s",
                eloc_id, workflow_step, status, pricing_direction, workflow_complete, can_remove,
                scheduled_iso or "none",
            )

            workflows.append({
                "eloc_id": eloc_id,
                "company_id": state.get("companyId"),
                "current_step": workflow_step,
                "step_status": status,
                "updated_at": str(state["modifiedAt"]) if state.get("modifiedAt") else None,
                "can_remove": can_remove,
                "steps": steps,
                "source": "portal",
                "pricing_direction": pricing_direction,
                "workflow_complete": workflow_complete,
            })
    except Exception as exc:
        logger.warning("  Failed to fetch portal workflows: %s", exc)

    logger.info("  Returning %d pricing workflows", len(workflows))
    return workflows


async def remove_pricing_workflow(eloc_id: str, company_id: int) -> bool:
    logger.info("remove_pricing_workflow (hide) eloc_id=%s company_id=%s", eloc_id, company_id)
    success = await onprem.hide_portal_eloc(eloc_id)
    if success:
        logger.info("  Hidden eloc_id=%s from client Portal UI", eloc_id)
    else:
        logger.warning("  Hide failed for eloc_id=%s", eloc_id)
    return success



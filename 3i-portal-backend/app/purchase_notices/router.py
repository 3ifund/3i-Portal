"""
3i Fund Portal — Purchase Notice Endpoints (User)
Signatory management + purchase notice prefill + submission with optional SMS verification.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from fastapi import status

from app.auth.dependencies import get_current_user
from app.auth.models import UserInfo
from app.config import settings
from app.purchase_notices.models import (
    CreateSignatoryRequest,
    PortalPurchaseNoticeRequest,
    UpdateSignatoryRequest,
    UpdateSignatoryDetailsRequest,
)
from app.purchase_notices import mongo_repository as repo
from app.purchase_notices import pg_repository as sig_repo
from app.onprem import client as onprem
from app.approval.repository import get_company_verification, get_included_contacts
from app.approval.router import create_approval_token
from app.approval.sms import send_approval_sms

logger = logging.getLogger("portal.purchase_notices")
router = APIRouter()


# ---- Company Signatories (names managed by admin, details entered by client) ----

@router.get("/signatories")
async def list_signatories(user: UserInfo = Depends(get_current_user)):
    """List signatories for the current user's company."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User has no company assigned")
    company_id = int(user.company_id)
    logger.info("GET /signatories — user=%s, company_id=%s", user.user_id, company_id)
    signatories = await sig_repo.get_company_signatories(company_id)
    logger.debug("GET /signatories — company_id=%s — returned %d signatories", company_id, len(signatories))
    return signatories


@router.put("/signatories/{signatory_id}")
async def update_signatory_details(
    signatory_id: int,
    request: UpdateSignatoryDetailsRequest,
    user: UserInfo = Depends(get_current_user),
):
    """Update signatory details (title, address, phone_number, signature_image) — client-entered."""
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User has no company assigned")
    company_id = int(user.company_id)
    updates = request.model_dump(exclude_none=True)
    logger.info("PUT /signatories/%s — user=%s, company=%s, updates=%s",
                signatory_id, user.user_id, company_id, list(updates.keys()))
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    ok = await sig_repo.update_company_signatory_details(company_id, signatory_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Signatory not found")
    return {"status": "updated"}


# ---- Purchase Notice Prefill ----

@router.get("/prefill/{symbol}/{pricing_period_id}")
async def get_prefill(
    symbol: str,
    pricing_period_id: int,
    shares: int = Query(..., gt=0),
    user: UserInfo = Depends(get_current_user),
):
    """
    Get all data needed to render a purchase notice.
    Merges DTS calculated fields + MongoDB template + PostgreSQL signatories.
    """
    logger.info("GET /prefill/%s/%d?shares=%d — user=%s, company=%s",
                symbol, pricing_period_id, shares, user.user_id, user.company_name)

    # 1. Get calculated fields from DTS
    logger.debug("Calling DTS get_purchase_notice_fields(%s, %d)", symbol, pricing_period_id)
    fields = await onprem.get_purchase_notice_fields(symbol, pricing_period_id)
    if not fields:
        logger.warning("DTS returned no data for %s / period %d", symbol, pricing_period_id)
        raise HTTPException(
            status_code=404,
            detail=f"No purchase notice data for {symbol} / period {pricing_period_id}",
        )
    logger.debug("DTS fields received: periodType=%s, exerciseDate=%s, withinWindow=%s, signer=%s",
                 fields.get("periodType"), fields.get("exerciseDate"),
                 fields.get("isWithinAcceptanceWindow"), fields.get("signerName"))

    # 2. Get template from MongoDB (company-specific, with legacy fallback)
    period_type = fields.get("periodType", "")
    company_id = int(user.company_id) if user.company_id else None
    logger.debug("Looking up template for company_id=%s, period_type=%s", company_id, period_type)
    template = await repo.get_template_by_period_type(period_type, company_id)
    body_text = template.get("body_text", "") if template else ""
    agreed_entity = template.get("agreed_accepted_entity", "") if template else ""
    logger.debug("Template found=%s, body_text_len=%d, entity=%s",
                 template is not None, len(body_text), agreed_entity)

    # 3. Get company signatories from PostgreSQL (admin-managed names, client-entered details)
    logger.debug("Loading company signatories for company_id=%s", company_id)
    signatories = await sig_repo.get_company_signatories(company_id) if company_id else []
    logger.debug("Found %d company signatories for company_id=%s", len(signatories), company_id)

    # 4. Return merged response
    logger.info("Prefill response ready: %s %s exercise=%s valuation=%s-%s settlement=%s shares=%d signatories=%d",
                symbol, period_type, fields.get("exerciseDate"), fields.get("valuationPeriodStart"),
                fields.get("valuationPeriodEnd"), fields.get("settlementDate"), shares, len(signatories))
    return {
        **fields,
        "body_text": body_text,
        "agreed_accepted_entity": agreed_entity,
        "shares": shares,
        "signatories": signatories,
    }


# ---- Portal-Initiated Purchase Notice Submission ----

@router.post("/submit")
async def submit_portal_purchase_notice(
    request: PortalPurchaseNoticeRequest,
    user: UserInfo = Depends(get_current_user),
):
    """
    Submit a portal-initiated purchase notice to DTS.
    DTS generates the PDF, creates eloc_id, writes to three_i_fund_portal MongoDB,
    and returns the eloc_id.
    """
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no company assigned",
        )

    logger.info(
        "POST /submit — user=%s symbol=%s period=%d shares=%d signatory=%s company_id=%s",
        user.user_id, request.symbol, request.pricing_period_id,
        request.shares, request.signatory_name, user.company_id,
    )

    payload = {
        **request.model_dump(),
        "company_id": int(user.company_id),
        "company_name": user.company_name or "",
        "submitted_by": user.user_id,
    }

    logger.debug(
        "POST /submit payload keys: %s",
        list(payload.keys()),
    )
    logger.debug(
        "POST /submit payload (core): symbol=%s, pricing_period_id=%s, shares=%s, "
        "company_id=%s, company_name=%s, signatory_name=%s, period_type=%s, "
        "exercise_date=%s, settlement_date=%s",
        payload.get("symbol"), payload.get("pricing_period_id"), payload.get("shares"),
        payload.get("company_id"), payload.get("company_name"), payload.get("signatory_name"),
        payload.get("period_type"), payload.get("exercise_date"), payload.get("settlement_date"),
    )

    # 1. Always submit to DTS first — creates ELOC at SignedContractToCompany / Pending
    company_id = int(user.company_id)
    try:
        result = await onprem.submit_portal_purchase_notice(payload)
    except Exception as exc:
        logger.error("Portal purchase notice submission failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unable to submit purchase notice: {exc}",
        )

    eloc_id = result.get("elocId") or result.get("eloc_id")
    logger.info("POST /submit — DTS created ELOC: eloc_id=%s at SignedContractToCompany/Pending", eloc_id)

    # 2. Check if company requires SMS verification
    requires_verification = await get_company_verification(company_id)
    logger.info("POST /submit — company_id=%s requires_verification=%s", company_id, requires_verification)

    if requires_verification:
        contacts = await get_included_contacts()
        if contacts:
            group_id = str(uuid.uuid4())
            company_name = user.company_name or ""
            amount = str(payload.get("shares", 0))

            logger.info("POST /submit — sending verification SMS to %d contacts, group=%s, eloc_id=%s",
                        len(contacts), group_id, eloc_id)

            for contact in contacts:
                token_result = await create_approval_token(
                    group_id=group_id,
                    contact_name=contact["name"],
                    contact_phone=contact["phone_number"],
                    company_name=company_name,
                    amount=amount,
                    eloc_id=eloc_id,
                )
                full_url = f"{settings.approval_base_url}{token_result['url']}"
                try:
                    await send_approval_sms(
                        contact["phone_number"], company_name, amount, full_url,
                    )
                except Exception as sms_exc:
                    logger.error("SMS send failed to %s: %s", contact["phone_number"], sms_exc)

            return {
                "status": "pending_verification",
                "eloc_id": eloc_id,
                "message": "Purchase notice sent for approval via SMS.",
            }

        logger.info("POST /submit — verification required but no included contacts, auto-accepting")

    # 3. Auto-accept: advance to SavedContractToSharePoint and set verified_by = "Auto"
    if eloc_id:
        try:
            accept_result = await onprem.accept_portal_eloc(eloc_id)
            logger.info("POST /submit — auto-accepted eloc_id=%s: %s", eloc_id, accept_result)
        except Exception as acc_exc:
            logger.error("Failed to auto-accept eloc_id=%s: %s", eloc_id, acc_exc, exc_info=True)

        try:
            await repo.set_verified_by(eloc_id, "Auto")
        except Exception as vb_exc:
            logger.error("Failed to set verified_by for eloc_id=%s: %s", eloc_id, vb_exc)

    logger.info("Portal purchase notice submitted and auto-accepted: %s", result)
    return result


@router.get("/documents/{eloc_id}/{step}")
async def get_portal_document(
    eloc_id: str,
    step: str,
    user: UserInfo = Depends(get_current_user),
):
    """
    Fetch document for a portal-initiated ELOC workflow step.
    Returns PDF data from three_i_fund_portal.eloc_data via DTS.
    """
    logger.info("GET /documents/%s/%s — user=%s", eloc_id, step, user.user_id)

    doc = await onprem.get_portal_eloc_document(eloc_id, step)
    if not doc:
        logger.warning("Document not found for eloc=%s step=%s", eloc_id, step)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found for this step",
        )

    logger.info("Document returned for eloc=%s step=%s", eloc_id, step)
    return doc


# ---- Purchase Confirmation Countersign ----

@router.get("/confirmation-prefill/{eloc_id}")
async def get_confirmation_prefill(
    eloc_id: str,
    user: UserInfo = Depends(get_current_user),
):
    """
    Get prefill data for countersigning a purchase confirmation.
    Reads VWAP pricing data + template + firm signature + company signatories.
    """
    logger.info("GET /confirmation-prefill/%s — user=%s company_id=%s", eloc_id, user.user_id, user.company_id)

    from app.database.mongo import get_db
    db = get_db()

    # 1. Load eloc_data from portal_3i
    eloc_data = await db.eloc_data.find_one({"eloc_id": eloc_id})
    if not eloc_data:
        raise HTTPException(status_code=404, detail=f"ELOC data not found: {eloc_id}")

    symbol = eloc_data.get("symbol", "")
    company_id = eloc_data.get("company_id")
    company_name = eloc_data.get("company_name", "")
    period_type = eloc_data.get("period_type", "")

    # 2. Load confirmation template
    template = await repo.get_confirmation_template_by_period_type(period_type, company_id)
    body_text = template.get("body_text", "") if template else ""
    agreed_accepted_entity = template.get("agreed_accepted_entity", company_name) if template else company_name

    # 3. Firm signature already stored in eloc_data from purchase notice submission
    #    DTS stores the signature image as raw base64 (no data URI prefix).
    #    The frontend needs a full data URI for <img> src rendering.
    firm_sig_image = eloc_data.get("firm_signatory_signature_image") or ""
    if firm_sig_image and not firm_sig_image.startswith("data:"):
        firm_sig_image = f"data:image/png;base64,{firm_sig_image}"
        logger.info("Confirmation prefill %s: added data URI prefix to firm signature image", eloc_id)
    logger.debug("Confirmation prefill %s: firm_sig name=%s, has_image=%s",
                 eloc_id, eloc_data.get("firm_signatory_name", ""), bool(firm_sig_image))

    firm_signature = {
        "name": eloc_data.get("firm_signatory_name", ""),
        "title": eloc_data.get("firm_signatory_title", ""),
        "address": eloc_data.get("firm_signatory_address", ""),
        "email": eloc_data.get("firm_signatory_email", ""),
        "signature_image": firm_sig_image,
    }

    # 4. Load company signatories from PostgreSQL
    signatories = []
    if company_id:
        signatories = await sig_repo.get_company_signatories(company_id)

    # 5. Build response
    result = {
        "eloc_id": eloc_id,
        "symbol": symbol,
        "company_id": company_id,
        "company_name": company_name,
        "period_type": period_type,
        # Template content
        "body_text": body_text,
        "agreed_accepted_entity": agreed_accepted_entity,
        # VWAP pricing data (from VwapPricingService results)
        "shares": eloc_data.get("shares", 0),
        "exercise_date": eloc_data.get("exercise_date", ""),
        "valuation_period_start": eloc_data.get("valuation_period_start", ""),
        "valuation_period_end": eloc_data.get("valuation_period_end", ""),
        "settlement_date": eloc_data.get("settlement_date", ""),
        "vwap_purchase_price": eloc_data.get("vwap_purchase_price"),
        "lowest_vwap": eloc_data.get("lowest_vwap"),
        "vwap_used": eloc_data.get("vwap_used"),
        "dollar_amount_calculated": eloc_data.get("dollar_amount_calculated"),
        # Firm signature (already signed)
        "firm_signature": firm_signature,
        # Company signatories (for countersign dropdown)
        "signatories": signatories,
    }

    logger.info("Confirmation prefill for %s: symbol=%s, vwap=%s, %d signatories",
                eloc_id, symbol, eloc_data.get("vwap_purchase_price"), len(signatories))
    return result


@router.post("/countersign")
async def submit_countersign(
    payload: dict,
    user: UserInfo = Depends(get_current_user),
):
    """
    Submit a countersigned purchase confirmation.
    Advances the Portal workflow past VwapNotificationToCompany.
    """
    eloc_id = payload.get("eloc_id", "")
    logger.info("POST /countersign — user=%s, eloc_id=%s", user.user_id, eloc_id)

    if not eloc_id:
        raise HTTPException(status_code=400, detail="eloc_id is required")

    signatory_name = payload.get("signatory_name", "")
    signatory_title = payload.get("signatory_title", "")
    signatory_signature_image = payload.get("signatory_signature_image")

    if not signatory_name:
        raise HTTPException(status_code=400, detail="Signatory name is required")

    from app.database.mongo import get_db
    db = get_db()

    # 1. Store countersign data in eloc_data
    from datetime import datetime, timezone
    update_fields = {
        "countersign_name": signatory_name,
        "countersign_title": signatory_title,
        "countersign_signature_image": signatory_signature_image,
        "countersigned_at": datetime.now(timezone.utc),
        "countersigned_by": user.user_id,
        "modified_at": datetime.now(timezone.utc),
    }
    await db.eloc_data.update_one(
        {"eloc_id": eloc_id},
        {"$set": update_fields},
    )
    logger.info("Countersign data stored for %s by %s", eloc_id, signatory_name)

    # 2. Supersede any pending SMS countersign tokens for this ELOC
    try:
        from app.countersign.repository import supersede_all_tokens_for_eloc
        await supersede_all_tokens_for_eloc(eloc_id)
    except Exception as sup_exc:
        logger.warning("Failed to supersede countersign tokens for %s: %s", eloc_id, sup_exc)

    # 3. Accept the current workflow step (VwapNotificationToCompany) via DTS
    try:
        result = await onprem.accept_portal_eloc(eloc_id)
        logger.info("Workflow advanced for %s: %s", eloc_id, result)
    except Exception as e:
        logger.error("Failed to advance workflow for %s: %s", eloc_id, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to advance workflow: {e}",
        )

    return {
        "status": "countersigned",
        "eloc_id": eloc_id,
        "signatory": signatory_name,
        "result": result,
    }

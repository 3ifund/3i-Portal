
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from fastapi import status

from app.auth.dependencies import get_current_user
from app.auth.models import UserInfo
from app.config import settings
from app.purchase_notices.models import (
    PortalPurchaseNoticeRequest,
    UpdateSignatoryDetailsRequest,
)
from app.purchase_notices import mongo_repository as repo
from app.onprem import client as onprem
from app.users import repository as users_repo
from app.approval.repository import get_company_verification, get_included_contacts
from app.approval.router import create_approval_token
from app.approval.sms import send_approval_sms

logger = logging.getLogger("portal.purchase_notices")
router = APIRouter()


async def _verify_eloc_ownership(eloc_id: str, user: UserInfo) -> None:
    if not user.company_id:
        raise HTTPException(status_code=400, detail="User has no company assigned")

    try:
        from app.database.mongo import get_db, is_connected
        if is_connected():
            db = get_db()
            eloc_data = await db.eloc_data.find_one({"eloc_id": eloc_id}, {"company_id": 1})
            if eloc_data:
                if eloc_data.get("company_id") != int(user.company_id):
                    logger.warning("Ownership denied: user company_id=%s, ELOC company_id=%s, eloc_id=%s",
                                    user.company_id, eloc_data.get("company_id"), eloc_id)
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Access denied: ELOC belongs to a different company",
                    )
                return
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Ownership check via MongoDB failed for eloc_id=%s: %s", eloc_id, exc)

    state = await onprem.get_eloc_state_by_id(eloc_id)
    if not state:
        logger.warning("Ownership check: ELOC %s not found", eloc_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="ELOC not found")
    if state.get("companyId") != int(user.company_id):
        logger.warning("Ownership denied: user company_id=%s, ELOC company_id=%s, eloc_id=%s",
                        user.company_id, state.get("companyId"), eloc_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: ELOC belongs to a different company",
        )



@router.get("/my-signatory")
async def get_my_signatory(user: UserInfo = Depends(get_current_user)):
    logger.info("GET /my-signatory — user=%s", user.user_id)
    sig = await users_repo.get_user_signatory(user.user_id)
    if not sig:
        raise HTTPException(status_code=404, detail="User not found")
    logger.info("GET /my-signatory — name=%s, has_title=%s, has_signature=%s",
                sig.get("signatory_name"), bool(sig.get("signatory_title")),
                bool(sig.get("signatory_signature_image")))
    return sig


@router.put("/my-signatory")
async def update_my_signatory(
    request: UpdateSignatoryDetailsRequest,
    user: UserInfo = Depends(get_current_user),
):
    raw = request.model_dump(exclude_none=True)
    updates = {}
    if "title" in raw:
        updates["signatory_title"] = raw["title"]
    if "address" in raw:
        updates["signatory_address"] = raw["address"]
    if "phone_number" in raw:
        updates["signatory_phone_number"] = raw["phone_number"]
    if "signature_image" in raw:
        updates["signatory_signature_image"] = raw["signature_image"]

    logger.info("PUT /my-signatory — user=%s, updates=%s", user.user_id, list(updates.keys()))
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    ok = await users_repo.update_signatory_details(user.user_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    logger.info("PUT /my-signatory — user=%s updated successfully", user.user_id)
    return {"status": "updated"}



@router.get("/prefill/{symbol}/{pricing_period_id}")
async def get_prefill(
    symbol: str,
    pricing_period_id: int,
    shares: int = Query(..., gt=0),
    backward: bool = Query(False),
    user: UserInfo = Depends(get_current_user),
):
    logger.info("GET /prefill/%s/%d?shares=%d&backward=%s — user=%s, company=%s",
                symbol, pricing_period_id, shares, backward, user.user_id, user.company_name)

    logger.info("Prefill %s/%d: calling DTS get_purchase_notice_fields", symbol, pricing_period_id)
    fields = await onprem.get_purchase_notice_fields(symbol, pricing_period_id)
    if not fields:
        logger.warning("Prefill %s/%d: DTS returned no data", symbol, pricing_period_id)
        raise HTTPException(
            status_code=404,
            detail=f"No purchase notice data for {symbol} / period {pricing_period_id}",
        )
    logger.info("Prefill %s/%d: DTS raw response keys: %s", symbol, pricing_period_id, list(fields.keys()))
    logger.info("Prefill %s/%d: DTS periodType=%s exerciseDate=%s settlementDate=%s",
                symbol, pricing_period_id, fields.get("periodType"), fields.get("exerciseDate"), fields.get("settlementDate"))
    logger.info("Prefill %s/%d: DTS valuationPeriodStart=%s valuationPeriodEnd=%s tradingDays=%s",
                symbol, pricing_period_id, fields.get("valuationPeriodStart"), fields.get("valuationPeriodEnd"), fields.get("tradingDays"))
    logger.info("Prefill %s/%d: DTS companyName=%s symbol=%s signerName=%s signerTitle=%s",
                symbol, pricing_period_id, fields.get("companyName"), fields.get("symbol"),
                fields.get("signerName"), fields.get("signerTitle"))
    logger.info("Prefill %s/%d: DTS isWithinAcceptanceWindow=%s acceptanceWindowStart=%s acceptanceWindowEnd=%s",
                symbol, pricing_period_id, fields.get("isWithinAcceptanceWindow"),
                fields.get("acceptanceWindowStart"), fields.get("acceptanceWindowEnd"))
    logger.info("Prefill %s/%d: DTS totalCommitmentRemaining=%s dollarCapPerNotice=%s pricingDirection=%s backwardVwapPrice=%s",
                symbol, pricing_period_id, fields.get("totalCommitmentRemaining"), fields.get("dollarCapPerNotice"),
                fields.get("pricingDirection"), fields.get("backwardVwapPrice"))

    is_backward = backward
    if not is_backward:
        try:
            shares_data = await onprem.get_shares_available(symbol)
            for p in shares_data.get("pricingPeriods", []):
                if p.get("pricingPeriodId") == pricing_period_id and p.get("isBackwardPricing"):
                    is_backward = True
                    logger.info("Prefill %s/%d: auto-detected backward pricing from shares-available", symbol, pricing_period_id)
                    break
        except Exception as exc:
            logger.warning("Prefill %s/%d: shares-available lookup failed (using backward=%s): %s",
                           symbol, pricing_period_id, backward, exc)
    logger.info("Prefill %s/%d: is_backward=%s (frontend=%s, auto-detect=%s)",
                symbol, pricing_period_id, is_backward, backward, is_backward and not backward)

    period_type = fields.get("periodType", "")
    company_id = int(user.company_id) if user.company_id else None
    if is_backward:
        logger.info("Prefill %s/%d: using backward template collection", symbol, pricing_period_id)
        template = await repo.get_backward_notice_template_by_period_type(period_type, company_id)
    else:
        logger.debug("Prefill %s/%d: using forward template collection", symbol, pricing_period_id)
        template = await repo.get_template_by_period_type(period_type, company_id)
    body_text = template.get("body_text", "") if template else ""
    agreed_entity = template.get("agreed_accepted_entity", "") if template else ""
    logger.info("Prefill %s/%d: template found=%s, is_backward=%s, body_text_len=%d, entity=%s",
                symbol, pricing_period_id, template is not None, is_backward, len(body_text), agreed_entity)

    signatory = await users_repo.get_user_signatory(user.user_id)
    logger.info("Prefill %s/%d: user signatory name=%s has_title=%s has_signature=%s",
                symbol, pricing_period_id,
                signatory.get("signatory_name") if signatory else None,
                bool(signatory.get("signatory_title")) if signatory else False,
                bool(signatory.get("signatory_signature_image")) if signatory else False)

    response = {
        **fields,
        "body_text": body_text,
        "agreed_accepted_entity": agreed_entity,
        "shares": shares,
        "signatory": signatory,
    }
    logger.info("Prefill %s/%d RESPONSE: exerciseDate=%s settlementDate=%s valuationStart=%s valuationEnd=%s tradingDays=%s",
                symbol, pricing_period_id, response.get("exerciseDate"), response.get("settlementDate"),
                response.get("valuationPeriodStart"), response.get("valuationPeriodEnd"), response.get("tradingDays"))
    logger.info("Prefill %s/%d RESPONSE: shares=%d periodType=%s pricingDirection=%s backwardVwapPrice=%s body_len=%d",
                symbol, pricing_period_id, shares, period_type,
                response.get("pricingDirection"), response.get("backwardVwapPrice"), len(body_text))
    return response



@router.post("/submit")
async def submit_portal_purchase_notice(
    request: PortalPurchaseNoticeRequest,
    user: UserInfo = Depends(get_current_user),
):
    if not user.company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no company assigned",
        )

    sig = await users_repo.get_user_signatory(user.user_id)
    if not sig or not sig.get("signatory_name"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Signatory name not set — contact your administrator",
        )

    logger.info(
        "POST /submit — user=%s symbol=%s period=%d shares=%d signatory=%s company_id=%s",
        user.user_id, request.symbol, request.pricing_period_id,
        request.shares, sig.get("signatory_name"), user.company_id,
    )

    payload = {
        **request.model_dump(),
        "company_id": int(user.company_id),
        "company_name": user.company_name or "",
        "submitted_by": user.user_id,
        "signatory_name": sig.get("signatory_name", ""),
        "signatory_title": sig.get("signatory_title", ""),
        "signatory_address": sig.get("signatory_address", ""),
        "signatory_signature_image": sig.get("signatory_signature_image"),
    }

    if payload.get("pricing_direction") != "Backward":
        try:
            shares_data = await onprem.get_shares_available(request.symbol)
            for p in shares_data.get("pricingPeriods", []):
                if p.get("pricingPeriodId") == request.pricing_period_id and p.get("isBackwardPricing"):
                    logger.info("POST /submit — auto-correcting pricing_direction to Backward for %s period %d",
                                request.symbol, request.pricing_period_id)
                    payload["pricing_direction"] = "Backward"
                    payload["backward_vwap_price"] = p.get("backwardVwapPrice")
                    logger.info("POST /submit — backward_vwap_price=%s", payload["backward_vwap_price"])
                    break
        except Exception as exc:
            logger.warning("POST /submit — shares-available lookup for auto-detect failed: %s", exc)

    logger.info("POST /submit payload keys: %s", list(payload.keys()))
    logger.info("POST /submit DATES: exercise_date=%s settlement_date=%s valuation_start=%s valuation_end=%s trading_days=%s",
                payload.get("exercise_date"), payload.get("settlement_date"),
                payload.get("valuation_period_start"), payload.get("valuation_period_end"), payload.get("trading_days"))
    logger.info("POST /submit DETAILS: symbol=%s period_type=%s pricing_period_id=%s shares=%s pricing_direction=%s backward_vwap_price=%s",
                payload.get("symbol"), payload.get("period_type"), payload.get("pricing_period_id"),
                payload.get("shares"), payload.get("pricing_direction"), payload.get("backward_vwap_price"))
    logger.info("POST /submit SIGNATORY: name=%s title=%s company=%s submitted_by=%s",
                payload.get("signatory_name"), payload.get("signatory_title"),
                payload.get("company_name"), payload.get("submitted_by"))

    company_id = int(user.company_id)
    try:
        result = await onprem.submit_portal_purchase_notice(payload)
    except onprem.ElocAlreadyPricingError as race:
        logger.warning(
            "POST /submit REJECT (concurrency): user=%s company=%s symbol=%s shares=%s — "
            "blocking elocId=%s step=%s",
            user.user_id, company_id, request.symbol, request.shares,
            race.blocking_eloc_id, race.blocking_workflow_step,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ELOC_ALREADY_PRICING",
                "message": str(race),
                "company_id": race.company_id,
                "blocking_eloc_id": race.blocking_eloc_id,
                "blocking_workflow_step": race.blocking_workflow_step,
            },
        )
    except Exception as exc:
        logger.error("Portal purchase notice submission failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unable to submit purchase notice: {exc}",
        )

    eloc_id = result.get("elocId") or result.get("eloc_id")
    logger.info("POST /submit — DTS created ELOC: eloc_id=%s at SignedContractToCompany/Pending", eloc_id)

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
    logger.info("GET /documents/%s/%s — user=%s", eloc_id, step, user.user_id)
    await _verify_eloc_ownership(eloc_id, user)

    doc = await onprem.get_portal_eloc_document(eloc_id, step)
    if not doc:
        logger.warning("Document not found for eloc=%s step=%s", eloc_id, step)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found for this step",
        )

    logger.info("Document returned for eloc=%s step=%s", eloc_id, step)
    return doc



@router.get("/confirmation-prefill/{eloc_id}")
async def get_confirmation_prefill(
    eloc_id: str,
    user: UserInfo = Depends(get_current_user),
):
    logger.info("GET /confirmation-prefill/%s — user=%s company_id=%s", eloc_id, user.user_id, user.company_id)
    await _verify_eloc_ownership(eloc_id, user)

    from app.database.mongo import get_db
    db = get_db()

    eloc_data = await db.eloc_data.find_one({"eloc_id": eloc_id})
    if not eloc_data:
        raise HTTPException(status_code=404, detail=f"ELOC data not found: {eloc_id}")

    symbol = eloc_data.get("symbol", "")
    company_id = eloc_data.get("company_id")
    company_name = eloc_data.get("company_name", "")
    period_type = eloc_data.get("period_type", "")

    template = await repo.get_confirmation_template_by_period_type(period_type, company_id)
    body_text = template.get("body_text", "") if template else ""
    agreed_accepted_entity = template.get("agreed_accepted_entity", company_name) if template else company_name

    if body_text and "{{" in body_text:
        shares_val = eloc_data.get("shares", 0)
        vwap_price_val = eloc_data.get("vwap_purchase_price")
        total_val = eloc_data.get("dollar_amount_calculated")

        tag_values = {
            "{{shares}}": f"{int(shares_val):,}" if shares_val else "",
            "{{exercise_date}}": eloc_data.get("exercise_date", ""),
            "{{valuation_period_start}}": eloc_data.get("valuation_period_start", ""),
            "{{valuation_period_end}}": eloc_data.get("valuation_period_end", ""),
            "{{settlement_date}}": eloc_data.get("settlement_date", ""),
            "{{vwap_purchase_price}}": f"${float(vwap_price_val):,.6f}" if vwap_price_val else "",
            "{{dollar_amount_calculated}}": f"${float(total_val):,.2f}" if total_val else "",
        }
        logger.info("Confirmation prefill %s: body_text contains '{{' — scanning for placeholder tags", eloc_id)
        logger.info("Confirmation prefill %s: available tag values: %s",
                     eloc_id, {k: v for k, v in tag_values.items() if v})
        tag_count = sum(1 for t in tag_values if t in body_text)
        logger.info("Confirmation prefill %s: found %d placeholder tag(s) to substitute", eloc_id, tag_count)
        for tag, value in tag_values.items():
            if tag in body_text:
                logger.info("Confirmation prefill %s: substituting %s → '%s'", eloc_id, tag, value)
                body_text = body_text.replace(tag, value)
        logger.info("Confirmation prefill %s: body_text substitution complete", eloc_id)
    else:
        logger.info("Confirmation prefill %s: no placeholder tags in body_text (length=%d)",
                     eloc_id, len(body_text) if body_text else 0)

    import time
    to_name = ""
    to_email = ""
    to_name_source = "(empty)"
    to_email_source = "(empty)"
    firm_signature_source = "snapshot"
    firm_signature = None
    recipients = None
    dts_call_elapsed_ms = 0.0
    dts_call_outcome = "(unknown)"
    logger.info("Confirmation prefill %s: calling DTS /api/portal/eloc/%s/document-recipients for live values",
                eloc_id, eloc_id)
    t_dts_start = time.monotonic()
    try:
        recipients = await onprem.get_document_recipients(eloc_id)
        dts_call_elapsed_ms = (time.monotonic() - t_dts_start) * 1000
        dts_call_outcome = "ok" if recipients else "not-found-404"
        logger.info(
            "Confirmation prefill %s: DTS round-trip finished in %.1fms (outcome=%s, recipients=%s)",
            eloc_id, dts_call_elapsed_ms, dts_call_outcome,
            "present" if recipients else "None",
        )
    except Exception as exc:
        dts_call_elapsed_ms = (time.monotonic() - t_dts_start) * 1000
        dts_call_outcome = f"exception:{type(exc).__name__}"
        logger.warning(
            "Confirmation prefill %s: DTS document-recipients call FAILED in %.1fms (non-fatal, "
            "page will render with Mongo snapshot for firm_signature and empty to_name/to_email): %s: %s",
            eloc_id, dts_call_elapsed_ms, type(exc).__name__, exc,
        )

    if recipients:
        to_name = recipients.get("to_name") or ""
        to_email = recipients.get("to_email") or ""
        to_name_source = recipients.get("to_name_source", "(empty)")
        to_email_source = recipients.get("to_email_source", "(empty)")

        dts_firm = recipients.get("firm_signature") or {}
        dts_firm_src = recipients.get("firm_signature_source") or {}
        firm_sig_image = dts_firm.get("signature_image_base64") or ""
        if firm_sig_image and not firm_sig_image.startswith("data:"):
            firm_sig_image = f"data:image/png;base64,{firm_sig_image}"
        firm_signature = {
            "name":            dts_firm.get("name", ""),
            "title":           dts_firm.get("title", ""),
            "address":         dts_firm.get("address", ""),
            "email":           dts_firm.get("email", ""),
            "signature_image": firm_sig_image,
        }
        srcs = {dts_firm_src.get(k) for k in ("name", "title", "address", "email", "signature_image")}
        if srcs <= {"live"}:
            firm_signature_source = "live"
        elif srcs <= {"snapshot", "(none)"}:
            firm_signature_source = "snapshot"
        else:
            firm_signature_source = "mixed"
        logger.info(
            "Confirmation prefill %s: applied DTS recipients — to_name=%r[%s], to_email=%r[%s], firm.email=%r[%s] (block_source=%s)",
            eloc_id, to_name, to_name_source, to_email, to_email_source,
            firm_signature.get("email"),
            dts_firm_src.get("email"),
            firm_signature_source,
        )
    else:
        firm_sig_image = eloc_data.get("firm_signatory_signature_image") or ""
        if firm_sig_image and not firm_sig_image.startswith("data:"):
            firm_sig_image = f"data:image/png;base64,{firm_sig_image}"
        firm_signature = {
            "name":            eloc_data.get("firm_signatory_name", ""),
            "title":           eloc_data.get("firm_signatory_title", ""),
            "address":         eloc_data.get("firm_signatory_address", ""),
            "email":           eloc_data.get("firm_signatory_email", ""),
            "signature_image": firm_sig_image,
        }
        firm_signature_source = "snapshot-fallback"
        logger.warning(
            "Confirmation prefill %s: using Mongo snapshot fallback (firm.name=%r, firm.email=%r); "
            "to_name and to_email will be empty",
            eloc_id, firm_signature.get("name"), firm_signature.get("email"),
        )
    logger.debug("Confirmation prefill %s: final firm_sig has_image=%s", eloc_id, bool(firm_signature.get("signature_image")))

    signatory = await users_repo.get_user_signatory(user.user_id)
    logger.info("Confirmation prefill %s: user signatory name=%s has_title=%s has_signature=%s",
                eloc_id,
                signatory.get("signatory_name") if signatory else None,
                bool(signatory.get("signatory_title")) if signatory else False,
                bool(signatory.get("signatory_signature_image")) if signatory else False)

    result = {
        "eloc_id": eloc_id,
        "symbol": symbol,
        "company_id": company_id,
        "company_name": company_name,
        "period_type": period_type,
        "body_text": body_text,
        "agreed_accepted_entity": agreed_accepted_entity,
        "shares": eloc_data.get("shares", 0),
        "exercise_date": eloc_data.get("exercise_date", ""),
        "valuation_period_start": eloc_data.get("valuation_period_start", ""),
        "valuation_period_end": eloc_data.get("valuation_period_end", ""),
        "settlement_date": eloc_data.get("settlement_date", ""),
        "vwap_purchase_price": eloc_data.get("vwap_purchase_price"),
        "lowest_vwap": eloc_data.get("lowest_vwap"),
        "vwap_used": eloc_data.get("vwap_used"),
        "dollar_amount_calculated": eloc_data.get("dollar_amount_calculated"),
        # Per-day VWAP grid + discount/closing-substitution detail (the same breakdown the Pricing Details PDF
        # renders), so the countersign page can show how the price was derived. Null when priced before it was captured.
        "pricing_breakdown": eloc_data.get("pricing_breakdown"),
        "to_name": to_name,
        "to_email": to_email,
        "to_name_source": to_name_source,
        "to_email_source": to_email_source,
        "firm_signature": firm_signature,
        "firm_signature_source": firm_signature_source,
        "signatory": signatory,
    }

    try:
        import json as _json
        response_size_bytes = len(_json.dumps(result, default=str).encode("utf-8"))
    except Exception:
        response_size_bytes = -1
    logger.info(
        "Confirmation prefill for %s: symbol=%s, vwap=%s, signatory=%s, "
        "to_name=%r[%s], to_email=%r[%s], firm.email=%r, firm_source=%s, "
        "dts_call_ms=%.1f, dts_outcome=%s, response_bytes=%d",
        eloc_id, symbol, eloc_data.get("vwap_purchase_price"),
        signatory.get("signatory_name") if signatory else None,
        to_name, to_name_source, to_email, to_email_source,
        firm_signature.get("email"), firm_signature_source,
        dts_call_elapsed_ms, dts_call_outcome, response_size_bytes,
    )
    return result


@router.post("/countersign")
async def submit_countersign(
    payload: dict,
    user: UserInfo = Depends(get_current_user),
):
    eloc_id = payload.get("eloc_id", "")
    logger.info("POST /countersign — user=%s, eloc_id=%s", user.user_id, eloc_id)

    if not eloc_id:
        raise HTTPException(status_code=400, detail="eloc_id is required")

    await _verify_eloc_ownership(eloc_id, user)

    sig = await users_repo.get_user_signatory(user.user_id)
    if not sig or not sig.get("signatory_name"):
        raise HTTPException(status_code=400, detail="Signatory name not set — contact your administrator")

    signatory_name = sig.get("signatory_name", "")
    signatory_title = sig.get("signatory_title", "")
    signatory_signature_image = sig.get("signatory_signature_image")

    from app.database.mongo import get_db
    db = get_db()

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    update_fields = {
        "countersign_name": signatory_name,
        "countersign_title": signatory_title,
        "countersign_signature_image": signatory_signature_image,
        "countersigned_at": now,
        "countersigned_by": user.user_id,
        "modified_at": now,
    }
    await db.eloc_data.update_one(
        {"eloc_id": eloc_id},
        {"$set": update_fields},
    )
    logger.info("Countersign data stored for %s by %s (%s)", eloc_id, signatory_name, user.user_id)

    try:
        from app.countersign.repository import supersede_all_tokens_for_eloc
        await supersede_all_tokens_for_eloc(eloc_id)
    except Exception as sup_exc:
        logger.warning("Failed to supersede countersign tokens for %s: %s", eloc_id, sup_exc)

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

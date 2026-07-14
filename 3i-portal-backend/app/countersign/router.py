
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse

from app.countersign.repository import (
    get_countersign_token,
    check_group_responded,
    supersede_group_tokens,
)
from app.onprem import client as onprem

logger = logging.getLogger("portal.countersign")

router = APIRouter()



def _fmt_currency(value):
    if value is None:
        return ""
    try:
        return f"${float(value):,.2f}"
    except (ValueError, TypeError):
        return str(value)


def _fmt_shares(value):
    if value is None:
        return ""
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return str(value)



@router.get("/countersign/{token}", response_class=HTMLResponse)
async def countersign_page(token: str):
    logger.info("Countersign page accessed: token=%s", token[:12] + "...")

    token_data = await get_countersign_token(token)
    if not token_data:
        logger.warning("Countersign token not found: %s", token[:12] + "...")
        return _error_page("Invalid Link", "This countersign link is not valid.")

    group_id = token_data["group_id"]
    status = token_data["status"]
    expires = token_data["expires_at"]

    if status != "pending":
        logger.info("Countersign token already used: %s status=%s", token[:12] + "...", status)
        if status == "superseded":
            responder = await check_group_responded(group_id)
            if responder:
                return _done_page(
                    "Already Countersigned",
                    f"This Purchase Confirmation was already countersigned by {responder['signatory_name']}.",
                )
        return _done_page(f"Already {status.title()}", f"This Purchase Confirmation has already been {status}.")

    group_responded = await check_group_responded(group_id)
    if group_responded:
        logger.info("Group %s already responded by %s", group_id, group_responded["signatory_name"])
        return _done_page(
            "Already Countersigned",
            f"This Purchase Confirmation was already countersigned by {group_responded['signatory_name']}.",
        )

    if expires and datetime.now(timezone.utc) > expires.replace(tzinfo=timezone.utc):
        logger.warning("Countersign token expired: %s", token[:12] + "...")
        return _error_page("Link Expired", "This countersign link has expired.")

    eloc_id = token_data["eloc_id"]
    company_name = token_data["company_name"]
    signatory_id = token_data["signatory_id"]
    signatory_name = token_data["signatory_name"]

    from app.database.mongo import get_db
    db = get_db()
    eloc_data = await db.eloc_data.find_one({"eloc_id": eloc_id})
    if not eloc_data:
        logger.error("ELOC data not found for countersign: eloc_id=%s", eloc_id)
        return _error_page("Data Not Found", "The Purchase Confirmation data could not be loaded.")

    from app.purchase_notices import mongo_repository as mongo_repo
    period_type = eloc_data.get("period_type", "")
    company_id = eloc_data.get("company_id")
    template = await mongo_repo.get_confirmation_template_by_period_type(period_type, company_id)
    body_text = template.get("body_text", "") if template else ""
    agreed_entity = template.get("agreed_accepted_entity", company_name) if template else company_name

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
            "{{dollar_amount_calculated}}": _fmt_currency(total_val),
        }
        logger.info("Countersign page %s: body_text contains '{{' — scanning for placeholder tags", eloc_id)
        logger.info("Countersign page %s: available tag values: %s",
                     eloc_id, {k: v for k, v in tag_values.items() if v})
        tag_count = sum(1 for t in tag_values if t in body_text)
        logger.info("Countersign page %s: found %d placeholder tag(s) to substitute", eloc_id, tag_count)
        for tag, value in tag_values.items():
            if tag in body_text:
                logger.info("Countersign page %s: substituting %s → '%s'", eloc_id, tag, value)
                body_text = body_text.replace(tag, value)
        logger.info("Countersign page %s: body_text substitution complete", eloc_id)
    else:
        logger.info("Countersign page %s: no placeholder tags in body_text (length=%d)",
                     eloc_id, len(body_text) if body_text else 0)

    from app.purchase_notices.pg_repository import get_company_signatories
    signatories = await get_company_signatories(company_id) if company_id else []
    signatory = next((s for s in signatories if s["id"] == signatory_id), None)

    sig_title = signatory.get("title", "") if signatory else ""
    sig_address = signatory.get("address", "") if signatory else ""
    sig_image = signatory.get("signature_image", "") if signatory else ""

    shares = _fmt_shares(eloc_data.get("shares"))
    exercise_date = eloc_data.get("exercise_date", "")
    period_start = eloc_data.get("valuation_period_start", "")
    period_end = eloc_data.get("valuation_period_end", "")
    settlement_date = eloc_data.get("settlement_date", "")
    vwap_price = _fmt_currency(eloc_data.get("vwap_purchase_price"))
    total_price = _fmt_currency(eloc_data.get("dollar_amount_calculated"))

    firm_name = eloc_data.get("firm_signatory_name", "")
    firm_title = eloc_data.get("firm_signatory_title", "")
    firm_address = eloc_data.get("firm_signatory_address", "")
    firm_email = eloc_data.get("firm_signatory_email", "")
    firm_sig_image = eloc_data.get("firm_signatory_signature_image", "")
    if firm_sig_image and not firm_sig_image.startswith("data:"):
        firm_sig_image = f"data:image/png;base64,{firm_sig_image}"
        logger.info("Countersign page %s: added data URI prefix to firm signature image", eloc_id)
    logger.debug("Countersign page %s: firm_sig name=%s, has_image=%s", eloc_id, firm_name, bool(firm_sig_image))

    to_name = eloc_data.get("company_signatory_name", signatory_name)
    to_email = eloc_data.get("to_email", "")

    dated = datetime.now(timezone.utc).strftime("%B %d, %Y")

    firm_entity = "3i, LP"

    firm_sig_html = ""
    if firm_sig_image:
        firm_sig_html = f'<img src="{_esc(firm_sig_image)}" style="max-height:50px; max-width:250px; background:#fff; padding:3px 6px; border-radius:3px;" alt="Firm Signature">'
    else:
        firm_sig_html = '<span style="display:inline-block; width:200px; border-bottom:1px solid #666; height:1.2em;"></span>'

    co_sig_html = ""
    if sig_image:
        co_sig_html = f'<img src="{_esc(sig_image)}" style="max-height:50px; max-width:250px; background:#fff; padding:3px 6px; border-radius:3px;" alt="Signature">'
    else:
        co_sig_html = '<span style="display:inline-block; width:200px; border-bottom:1px solid #666; height:1.2em;"></span>'

    logger.info("Rendering countersign page: eloc=%s, signatory=%s, company=%s, vwap=%s",
                eloc_id, signatory_name, company_name, vwap_price)

    return _countersign_page(
        token=token,
        company_name=company_name,
        agreed_entity=agreed_entity,
        to_name=to_name,
        to_email=to_email,
        body_text=body_text,
        shares=shares,
        exercise_date=exercise_date,
        period_start=period_start,
        period_end=period_end,
        settlement_date=settlement_date,
        vwap_price=vwap_price,
        total_price=total_price,
        dated=dated,
        firm_entity=firm_entity,
        firm_name=firm_name,
        firm_title=firm_title,
        firm_address=firm_address,
        firm_email=firm_email,
        firm_sig_html=firm_sig_html,
        signatory_name=signatory_name,
        signatory_title=sig_title,
        co_sig_html=co_sig_html,
    )



@router.post("/countersign/{token}/respond", response_class=HTMLResponse)
async def countersign_respond(token: str):
    logger.info("Countersign response: token=%s", token[:12] + "...")

    token_data = await get_countersign_token(token)
    if not token_data:
        return _error_page("Invalid Link", "This countersign link is not valid.")

    if token_data["status"] != "pending":
        return _done_page(
            f"Already {token_data['status'].title()}",
            f"This Purchase Confirmation has already been {token_data['status']}.",
        )

    expires = token_data.get("expires_at")
    if expires and datetime.now(timezone.utc) > expires.replace(tzinfo=timezone.utc):
        logger.warning("Countersign token expired on POST: %s", token[:12] + "...")
        return _error_page("Link Expired", "This countersign link has expired.")

    group_id = token_data["group_id"]
    signatory_id = token_data["signatory_id"]
    signatory_name = token_data["signatory_name"]
    signatory_phone = token_data["signatory_phone"]
    company_name = token_data["company_name"]
    eloc_id = token_data["eloc_id"]

    from app.countersign.repository import try_claim_token
    claimed = await try_claim_token(token, "approved")
    if not claimed:
        logger.info("Countersign atomic claim failed — token %s already claimed", token[:12] + "...")
        group_responded = await check_group_responded(group_id)
        if group_responded:
            return _done_page(
                "Already Countersigned",
                f"This Purchase Confirmation was already countersigned by {group_responded['signatory_name']}.",
            )
        return _done_page("Already Countersigned", "This Purchase Confirmation has already been countersigned.")
    logger.info("Countersign atomic claim succeeded: token=%s, signatory=%s", token[:12] + "...", signatory_name)

    await supersede_group_tokens(group_id, token)

    from app.purchase_notices.pg_repository import get_company_signatories
    from app.database.mongo import get_db

    db = get_db()
    eloc_data = await db.eloc_data.find_one({"eloc_id": eloc_id})
    company_id = eloc_data.get("company_id") if eloc_data else None

    sig_title = ""
    sig_image = None
    if company_id:
        signatories = await get_company_signatories(company_id)
        signatory = next((s for s in signatories if s["id"] == signatory_id), None)
        if signatory:
            sig_title = signatory.get("title", "")
            sig_image = signatory.get("signature_image")

    countersigned_by = f"{signatory_name} ({signatory_phone})"
    now = datetime.now(timezone.utc)
    update_fields = {
        "countersign_name": signatory_name,
        "countersign_title": sig_title,
        "countersign_signature_image": sig_image,
        "countersigned_at": now,
        "countersigned_by": countersigned_by,
        "modified_at": now,
    }
    await db.eloc_data.update_one(
        {"eloc_id": eloc_id},
        {"$set": update_fields},
    )
    logger.info("Countersign data stored for %s by %s", eloc_id, countersigned_by)

    try:
        result = await onprem.accept_portal_eloc(eloc_id)
        logger.info("DTS accept successful after countersign: eloc_id=%s result=%s", eloc_id, result)
    except Exception as exc:
        logger.error("DTS accept failed after countersign: eloc_id=%s error=%s", eloc_id, exc, exc_info=True)
        return _error_page(
            "Submission Error",
            f"The Purchase Confirmation was countersigned but workflow advance failed: {exc}. Please contact support.",
        )

    return _done_page(
        "Countersigned",
        f"Purchase Confirmation for {company_name} has been countersigned by {signatory_name}.",
    )



def _esc(s):
    if not s:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _countersign_page(
    token, company_name, agreed_entity, to_name, to_email,
    body_text, shares, exercise_date, period_start, period_end,
    settlement_date, vwap_price, total_price, dated,
    firm_entity, firm_name, firm_title, firm_address, firm_email, firm_sig_html,
    signatory_name, signatory_title, co_sig_html,
):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Purchase Confirmation Countersign — 3i Fund</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f4f6f8; min-height: 100vh; padding: 20px; color: #2c3e50; }}
        .container {{ max-width: 700px; margin: 0 auto; }}
        .logo-bar {{ text-align: center; padding: 16px 0; margin-bottom: 16px; }}
        .logo-bar span {{ font-size: 1.1rem; font-weight: 700; color: #1a3a5c; }}
        .document {{ background: #fff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); padding: 32px 28px; margin-bottom: 20px; }}
        .doc-title {{ text-align: center; font-size: 1.1rem; font-weight: 700; color: #1a3a5c; margin: 0 0 1.5rem; text-transform: uppercase; letter-spacing: 0.03em; }}
        .header-block {{ margin-bottom: 1.25rem; }}
        .field-row {{ display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.35rem; font-size: 0.9rem; }}
        .field-label {{ font-weight: 600; color: #6b7280; min-width: 60px; }}
        .field-value {{ color: #2c3e50; }}
        .body-text {{ font-size: 0.92rem; line-height: 1.65; color: #2c3e50; margin-bottom: 1.25rem; }}
        .fields-table {{ width: 100%; border-collapse: collapse; margin-bottom: 1.25rem; }}
        .fields-table td {{ padding: 0.5rem 0.75rem; border-bottom: 1px solid #e5e7eb; font-size: 0.9rem; }}
        .fields-table td:first-child {{ font-weight: 600; color: #6b7280; width: 260px; }}
        .fields-table td:last-child {{ color: #2c3e50; }}
        .sig-block {{ border-top: 1px solid #d1d5db; padding-top: 1.25rem; margin-top: 1.25rem; }}
        .block-title {{ font-size: 0.85rem; font-weight: 600; color: #6b7280; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.75rem; }}
        .sig-line {{ display: inline-block; width: 200px; border-bottom: 1px solid #666; height: 1.2em; }}
        .sub-label {{ color: #6b7280; font-size: 0.85rem; }}

        /* Legal disclaimer */
        .disclaimer {{ background: #fff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); padding: 28px; margin-bottom: 20px; }}
        .disclaimer-title {{ font-size: 1rem; font-weight: 700; color: #1a3a5c; margin-bottom: 1rem; }}
        .disclaimer-scroll {{ max-height: 350px; overflow-y: auto; padding: 1rem; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; font-size: 0.92rem; line-height: 1.65; color: #2c3e50; margin-bottom: 1rem; }}
        .disclaimer-scroll h4 {{ font-size: 0.9rem; font-weight: 600; color: #1a3a5c; margin: 1.25rem 0 0.4rem; }}
        .disclaimer-scroll p {{ margin-bottom: 0.5rem; }}
        .warning {{ text-align: center; font-weight: 700; color: #dc2626; font-size: 0.95rem; margin-bottom: 1rem; letter-spacing: 0.03em; }}
        .terms-table {{ width: 100%; border-collapse: collapse; margin: 0.5rem 0 1rem; }}
        .terms-table td {{ padding: 0.3rem 0.5rem; border-bottom: 1px solid #e5e7eb; font-size: 0.88rem; }}
        .terms-table td:first-child {{ font-weight: 600; color: #6b7280; width: 160px; }}
        .checkbox-label {{ display: flex; align-items: flex-start; gap: 0.6rem; padding: 0.75rem; background: #fef2f2; border-left: 3px solid #dc2626; font-size: 0.9rem; line-height: 1.5; color: #2c3e50; cursor: pointer; border-radius: 0 6px 6px 0; }}
        .checkbox-label input[type="checkbox"] {{ margin-top: 0.2rem; flex-shrink: 0; width: 16px; height: 16px; cursor: pointer; }}
        .actions {{ text-align: center; margin-top: 20px; }}
        .btn {{ padding: 14px 32px; border: none; border-radius: 8px; font-size: 1rem; font-weight: 700; cursor: pointer; transition: opacity 0.15s; }}
        .btn:active {{ opacity: 0.8; }}
        .btn:disabled {{ opacity: 0.5; cursor: not-allowed; }}
        .btn-accept {{ background: #27ae60; color: #fff; }}
        .btn-secondary {{ background: #6b7280; color: #fff; margin-right: 12px; }}
        .submitting {{ opacity: 0.6; pointer-events: none; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="logo-bar"><span>3i Fund Portal</span></div>

        <!-- Purchase Confirmation Document -->
        <div class="document">
            <h2 class="doc-title">FORM OF VWAP PURCHASE CONFIRMATION</h2>

            <div class="header-block">
                <div class="field-row">
                    <span class="field-label">To:</span>
                    <span class="field-value">{_esc(to_name)}</span>
                </div>
                <div class="field-row">
                    <span class="field-label">E-mail:</span>
                    <span class="field-value">{_esc(to_email)}</span>
                </div>
            </div>

            <div class="body-text">{_esc(body_text).replace(chr(10), '<br>')}</div>

            <table class="fields-table">
                <tr><td>VWAP Purchase Share Amount (number of Shares):</td><td>{_esc(shares)}</td></tr>
                <tr><td>VWAP Purchase Exercise Date:</td><td>{_esc(exercise_date)}</td></tr>
                <tr><td>VWAP Purchase Period start date:</td><td>{_esc(period_start)}</td></tr>
                <tr><td>VWAP Purchase Period end date:</td><td>{_esc(period_end)}</td></tr>
                <tr><td>VWAP Purchase Settlement Date:</td><td>{_esc(settlement_date)}</td></tr>
                <tr><td>VWAP Purchase Price (per Share):</td><td>{_esc(vwap_price)}</td></tr>
                <tr><td>Total Aggregate VWAP Purchase Price:</td><td>{_esc(total_price)}</td></tr>
            </table>

            <!-- Firm Signature Block (read-only, already signed) -->
            <div class="sig-block">
                <div class="field-row">
                    <span class="field-label">Dated:</span>
                    <span class="field-value">{_esc(dated)}</span>
                </div>
                <div class="block-title" style="margin-top:0.75rem;">{_esc(firm_entity)}</div>
                <p class="sub-label" style="margin:0 0 0.5rem;">By: 3i Management LLC, as Manager</p>
                <div class="field-row" style="align-items:flex-start;">
                    <span class="field-label" style="margin-top:0.25rem;">By:</span>
                    {firm_sig_html}
                </div>
                <div class="field-row"><span class="field-label">Name:</span><span class="field-value">{_esc(firm_name)}</span></div>
                <div class="field-row"><span class="field-label">Title:</span><span class="field-value">{_esc(firm_title)}</span></div>
                <div class="field-row"><span class="field-label">Address:</span><span class="field-value">{_esc(firm_address)}</span></div>
                <div class="field-row"><span class="field-label">Email:</span><span class="field-value">{_esc(firm_email)}</span></div>
            </div>

            <!-- Company Countersign Block (pre-filled from signatory data) -->
            <div class="sig-block">
                <div class="block-title">AGREED AND ACCEPTED:</div>
                <p class="field-value" style="font-weight:600; margin-bottom:0.75rem;">{_esc(agreed_entity)}</p>
                <div class="field-row" style="align-items:flex-start;">
                    <span class="field-label" style="margin-top:0.25rem;">By:</span>
                    {co_sig_html}
                </div>
                <div class="field-row"><span class="field-label">Name:</span><span class="field-value">{_esc(signatory_name)}</span></div>
                <div class="field-row"><span class="field-label">Title:</span><span class="field-value">{_esc(signatory_title)}</span></div>
            </div>
        </div>

        <!-- Legal Disclaimer -->
        <div class="disclaimer">
            <div class="disclaimer-title">Purchase Confirmation Countersign</div>
            <div class="disclaimer-scroll">
                <p class="warning">PLEASE READ CAREFULLY BEFORE SUBMITTING</p>

                <p>By clicking &ldquo;Accept and Submit&rdquo; below, you are countersigning the VWAP Purchase
                Confirmation under the Common Stock Purchase Agreement (the &ldquo;Agreement&rdquo;) between
                <strong>{_esc(company_name)}</strong> (the &ldquo;Company&rdquo;) and the Investor.</p>

                <h4>Purchase Confirmation Terms</h4>
                <table class="terms-table">
                    <tr><td>Shares:</td><td>{_esc(shares)}</td></tr>
                    <tr><td>VWAP Price:</td><td>{_esc(vwap_price)}</td></tr>
                    <tr><td>Total Price:</td><td>{_esc(total_price)}</td></tr>
                    <tr><td>Settlement Date:</td><td>{_esc(settlement_date)}</td></tr>
                </table>

                <h4>Binding Agreement</h4>
                <p>This countersignature, once submitted, constitutes your <strong>acceptance</strong>
                of the VWAP Purchase Confirmation and the pricing terms therein. Your electronic
                submission shall have the same legal force and effect as a manually executed document.</p>
            </div>

            <label class="checkbox-label">
                <input type="checkbox" id="confirm-checkbox" onchange="document.getElementById('submit-btn').disabled = !this.checked;">
                <span>I have read and understand the above terms. I confirm that I am authorized to
                countersign this Purchase Confirmation on behalf of <strong>{_esc(company_name)}</strong>.</span>
            </label>
        </div>

        <!-- Action -->
        <div class="actions">
            <form id="countersign-form" method="POST" action="/countersign/{token}/respond">
                <button type="submit" id="submit-btn" class="btn btn-accept" disabled
                        onclick="this.disabled=true; this.textContent='Submitting...'; this.form.classList.add('submitting'); this.form.submit();">
                    Accept and Submit
                </button>
            </form>
        </div>
    </div>
</body>
</html>"""


def _error_page(title, message):
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{title}</title>
<style>* {{ box-sizing: border-box; margin: 0; padding: 0; }} body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f4f6f8; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }} .card {{ background: #fff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); padding: 32px 24px; max-width: 400px; width: 100%; text-align: center; }} h2 {{ color: #c0392b; margin-bottom: 12px; }} p {{ color: #666; }}</style>
</head><body><div class="card"><h2>{title}</h2><p>{message}</p></div></body></html>"""


def _done_page(title, message):
    color = "#27ae60" if "Countersigned" in title else "#1a3a5c"
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{title}</title>
<style>* {{ box-sizing: border-box; margin: 0; padding: 0; }} body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f4f6f8; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }} .card {{ background: #fff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); padding: 32px 24px; max-width: 400px; width: 100%; text-align: center; }} h2 {{ color: {color}; margin-bottom: 12px; }} p {{ color: #666; }}</style>
</head><body><div class="card"><h2>{title}</h2><p>{message}</p></div></body></html>"""


import uuid
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse

from app.database.postgres import get_pool
from app.onprem import client as onprem
from app.purchase_notices import mongo_repository as mongo_repo

logger = logging.getLogger("portal.approval")

router = APIRouter()

TOKEN_EXPIRY_HOURS = 24


def _esc(s):
    if not s:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


async def create_approval_token(
    group_id: str,
    contact_name: str,
    contact_phone: str,
    company_name: str,
    amount: str,
    eloc_id: str,
) -> dict:
    pool = get_pool()
    token = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=TOKEN_EXPIRY_HOURS)

    await pool.execute("""
        INSERT INTO approval_tokens
            (token, group_id, contact_name, contact_phone, company_name, amount, status, eloc_id, created_at, expires_at)
        VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7, $8, $9)
    """, token, group_id, contact_name, contact_phone, company_name, amount, eloc_id, now, expires)

    logger.info("Approval token created: %s for %s → %s (%s) eloc_id=%s",
                token, company_name, contact_name, contact_phone, eloc_id)
    return {"token": token, "url": f"/approve/{token}"}


@router.get("/approve/{token}", response_class=HTMLResponse)
async def approval_page(token: str):
    logger.info("Approval page accessed: %s", token)
    pool = get_pool()

    row = await pool.fetchrow(
        "SELECT token, group_id, contact_name, company_name, amount, status, eloc_id, expires_at FROM approval_tokens WHERE token = $1",
        token,
    )

    if not row:
        logger.warning("Approval token not found: %s", token)
        return _error_page("Invalid Link", "This approval link is not valid.")

    group_id = row["group_id"]
    status = row["status"]
    expires = row["expires_at"]

    if status != "pending":
        logger.info("Approval token already used: %s status=%s", token, status)
        if status == "superseded":
            responder = await pool.fetchrow(
                "SELECT contact_name, status FROM approval_tokens WHERE group_id = $1 AND status IN ('approved', 'rejected')",
                group_id,
            )
            if responder:
                return _done_page(
                    "Already Responded",
                    f"This purchase notice was already {responder['status']} by {responder['contact_name']}.",
                )
        return _done_page(f"Already {status.title()}", f"This purchase notice has already been {status}.")

    group_responded = await pool.fetchrow(
        "SELECT contact_name, status FROM approval_tokens WHERE group_id = $1 AND status IN ('approved', 'rejected')",
        group_id,
    )
    if group_responded:
        logger.info("Group %s already responded by %s", group_id, group_responded["contact_name"])
        return _done_page(
            "Already Responded",
            f"This purchase notice was already {group_responded['status']} by {group_responded['contact_name']}.",
        )

    if expires and datetime.now(timezone.utc) > expires.replace(tzinfo=timezone.utc):
        logger.warning("Approval token expired: %s", token)
        return _error_page("Link Expired", "This approval link has expired.")

    company_name = row["company_name"]
    amount = row["amount"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>3i Fund — Purchase Notice Approval</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f4f6f8; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }}
        .card {{ background: #fff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); padding: 32px 24px; max-width: 400px; width: 100%; text-align: center; }}
        .logo {{ font-size: 1.1rem; font-weight: 700; color: #1a3a5c; margin-bottom: 24px; }}
        .question {{ font-size: 1.15rem; line-height: 1.6; color: #2c3e50; margin-bottom: 32px; }}
        .company {{ font-weight: 700; color: #1a3a5c; }}
        .amount {{ font-weight: 700; color: #1a3a5c; }}
        .buttons {{ display: flex; gap: 16px; }}
        .btn {{ flex: 1; padding: 16px; border: none; border-radius: 8px; font-size: 1.1rem; font-weight: 700; cursor: pointer; transition: opacity 0.15s; }}
        .btn:active {{ opacity: 0.8; }}
        .btn-accept {{ background: #27ae60; color: #fff; }}
        .btn-reject {{ background: #c0392b; color: #fff; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="logo">3i Fund</div>
        <p class="question">Do you agree to accept a purchase notice from <span class="company">{_esc(company_name)}</span> in the amount <span class="amount">${_esc(amount)}</span>?</p>
        <div class="buttons">
            <form method="POST" action="/approve/{token}/respond" style="flex:1;display:flex">
                <input type="hidden" name="action" value="approved">
                <button type="submit" class="btn btn-accept" style="flex:1">Accept</button>
            </form>
            <form method="POST" action="/approve/{token}/respond" style="flex:1;display:flex">
                <input type="hidden" name="action" value="rejected">
                <button type="submit" class="btn btn-reject" style="flex:1">Reject</button>
            </form>
        </div>
    </div>
</body>
</html>"""


@router.post("/approve/{token}/respond", response_class=HTMLResponse)
async def approval_respond(token: str, action: str = Form(...)):
    logger.info("Approval response: token=%s action=%s", token, action)
    pool = get_pool()

    row = await pool.fetchrow(
        "SELECT token, group_id, contact_name, contact_phone, status, company_name, amount, eloc_id FROM approval_tokens WHERE token = $1",
        token,
    )

    if not row:
        return _error_page("Invalid Link", "This approval link is not valid.")

    if row["status"] != "pending":
        return _done_page(f"Already {row['status'].title()}", f"This purchase notice has already been {row['status']}.")

    if action not in ("approved", "rejected"):
        return _error_page("Invalid Action", "Invalid response.")

    group_id = row["group_id"]
    contact_name = row["contact_name"]
    contact_phone = row["contact_phone"]
    company_name = row["company_name"]
    amount = row["amount"]
    eloc_id = row["eloc_id"]
    now = datetime.now(timezone.utc)

    claimed = await pool.fetchrow(
        "UPDATE approval_tokens SET status = $1, responded_at = $2 WHERE token = $3 AND status = 'pending' RETURNING token, contact_name",
        action, now, token,
    )
    if not claimed:
        logger.info("Approval atomic claim failed — token %s already claimed", token)
        group_responded = await pool.fetchrow(
            "SELECT contact_name, status FROM approval_tokens WHERE group_id = $1 AND status IN ('approved', 'rejected')",
            group_id,
        )
        if group_responded:
            return _done_page(
                "Already Responded",
                f"This purchase notice was already {group_responded['status']} by {group_responded['contact_name']}.",
            )
        return _done_page("Already Responded", "This purchase notice has already been responded to.")
    logger.info("Approval atomic claim succeeded: token=%s, action=%s, contact=%s", token, action, contact_name)

    await pool.execute(
        "UPDATE approval_tokens SET status = 'superseded', responded_at = $1 WHERE group_id = $2 AND token != $3 AND status = 'pending'",
        now, group_id, token,
    )

    verified_by = f"{contact_name} ({contact_phone})"
    logger.info("Approval %s by %s: group=%s company=%s amount=%s eloc_id=%s",
                action, verified_by, group_id, company_name, amount, eloc_id)

    if action == "approved":
        try:
            result = await onprem.accept_portal_eloc(eloc_id)
            logger.info("DTS accept successful after approval: eloc_id=%s result=%s", eloc_id, result)

            await mongo_repo.set_verified_by(eloc_id, verified_by)

        except Exception as exc:
            logger.error("DTS accept failed after approval: eloc_id=%s error=%s", eloc_id, exc, exc_info=True)
            return _error_page(
                "Submission Error",
                f"The purchase notice was approved but workflow advance failed: {exc}. Please contact support.",
            )

        return _done_page("Accepted", f"Purchase notice from {company_name} for ${amount} has been accepted and submitted.")

    else:
        try:
            result = await onprem.reject_portal_eloc(eloc_id)
            logger.info("DTS reject successful: eloc_id=%s result=%s", eloc_id, result)
        except Exception as exc:
            logger.error("DTS reject failed: eloc_id=%s error=%s", eloc_id, exc, exc_info=True)
            return _error_page(
                "Rejection Error",
                f"The purchase notice rejection could not be processed: {exc}. Please contact support.",
            )

        return _done_page("Rejected", f"Purchase notice from {company_name} for ${amount} has been rejected.")


def _error_page(title, message):
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{_esc(title)}</title>
<style>* {{ box-sizing: border-box; margin: 0; padding: 0; }} body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f4f6f8; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }} .card {{ background: #fff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); padding: 32px 24px; max-width: 400px; width: 100%; text-align: center; }} h2 {{ color: #c0392b; margin-bottom: 12px; }} p {{ color: #666; }}</style>
</head><body><div class="card"><h2>{_esc(title)}</h2><p>{_esc(message)}</p></div></body></html>"""


def _done_page(title, message):
    color = "#27ae60" if "Accepted" in title else "#c0392b" if "Rejected" in title else "#1a3a5c"
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{_esc(title)}</title>
<style>* {{ box-sizing: border-box; margin: 0; padding: 0; }} body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f4f6f8; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }} .card {{ background: #fff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); padding: 32px 24px; max-width: 400px; width: 100%; text-align: center; }} h2 {{ color: {color}; margin-bottom: 12px; }} p {{ color: #666; }}</style>
</head><body><div class="card"><h2>{_esc(title)}</h2><p>{_esc(message)}</p></div></body></html>"""

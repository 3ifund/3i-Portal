"""Purchase notice approval — token-based mobile approval page and response endpoint."""

import uuid
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse
from app.database.postgres import get_pool

logger = logging.getLogger("portal.approval")

router = APIRouter()

TOKEN_EXPIRY_HOURS = 24


async def create_approval_token(eloc_deal_id: int, company_name: str, amount: str) -> dict:
    """Create an approval token. Called internally when a purchase notice is submitted."""
    pool = get_pool()
    token = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=TOKEN_EXPIRY_HOURS)

    await pool.execute("""
        INSERT INTO approval_tokens (token, eloc_deal_id, company_name, amount, status, created_at, expires_at)
        VALUES ($1, $2, $3, $4, 'pending', $5, $6)
    """, token, eloc_deal_id, company_name, amount, now, expires)

    logger.info(f"Approval token created: {token} for {company_name} ${amount} (deal {eloc_deal_id})")
    return {"token": token, "url": f"/approve/{token}"}


@router.get("/approve/{token}", response_class=HTMLResponse)
async def approval_page(token: str):
    """Serve the mobile approval page."""
    logger.info(f"Approval page accessed: {token}")
    pool = get_pool()

    row = await pool.fetchrow(
        "SELECT token, eloc_deal_id, company_name, amount, status, expires_at FROM approval_tokens WHERE token = $1",
        token,
    )

    if not row:
        logger.warning(f"Approval token not found: {token}")
        return _error_page("Invalid Link", "This approval link is not valid.")

    status = row["status"]
    expires = row["expires_at"]

    if status != "pending":
        logger.info(f"Approval token already used: {token} status={status}")
        return _done_page(f"Already {status.title()}", f"This purchase notice has already been {status}.")

    if expires and datetime.now(timezone.utc) > expires.replace(tzinfo=timezone.utc):
        logger.warning(f"Approval token expired: {token}")
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
        <p class="question">Do you agree to accept a purchase notice from <span class="company">{company_name}</span> in the amount <span class="amount">${amount}</span>?</p>
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
    """Handle approval or rejection."""
    logger.info(f"Approval response: token={token} action={action}")
    pool = get_pool()

    row = await pool.fetchrow(
        "SELECT token, status, company_name, amount FROM approval_tokens WHERE token = $1",
        token,
    )

    if not row:
        return _error_page("Invalid Link", "This approval link is not valid.")

    if row["status"] != "pending":
        return _done_page(f"Already {row['status'].title()}", f"This purchase notice has already been {row['status']}.")

    if action not in ("approved", "rejected"):
        return _error_page("Invalid Action", "Invalid response.")

    await pool.execute(
        "UPDATE approval_tokens SET status = $1, responded_at = $2 WHERE token = $3",
        action, datetime.now(timezone.utc), token,
    )

    logger.info(f"Approval {action}: token={token} company={row['company_name']} amount={row['amount']}")

    if action == "approved":
        return _done_page("Accepted", f"Purchase notice from {row['company_name']} for ${row['amount']} has been accepted.")
    else:
        return _done_page("Rejected", f"Purchase notice from {row['company_name']} for ${row['amount']} has been rejected.")


def _error_page(title, message):
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{title}</title>
<style>* {{ box-sizing: border-box; margin: 0; padding: 0; }} body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f4f6f8; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }} .card {{ background: #fff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); padding: 32px 24px; max-width: 400px; width: 100%; text-align: center; }} h2 {{ color: #c0392b; margin-bottom: 12px; }} p {{ color: #666; }}</style>
</head><body><div class="card"><h2>{title}</h2><p>{message}</p></div></body></html>"""


def _done_page(title, message):
    color = "#27ae60" if "Accepted" in title else "#c0392b" if "Rejected" in title else "#1a3a5c"
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{title}</title>
<style>* {{ box-sizing: border-box; margin: 0; padding: 0; }} body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f4f6f8; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }} .card {{ background: #fff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); padding: 32px 24px; max-width: 400px; width: 100%; text-align: center; }} h2 {{ color: {color}; margin-bottom: 12px; }} p {{ color: #666; }}</style>
</head><body><div class="card"><h2>{title}</h2><p>{message}</p></div></body></html>"""

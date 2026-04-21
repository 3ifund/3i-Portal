"""Twilio SMS sender for purchase notice approval notifications."""

import asyncio
import logging
from app.config import settings

logger = logging.getLogger("portal.approval.sms")

_twilio_client = None


def _get_twilio_client():
    """Get or create a cached Twilio client (reuses HTTP connections)."""
    global _twilio_client
    if _twilio_client is None:
        from twilio.rest import Client
        logger.info("Creating Twilio client (approval) — account_sid=%s...",
                     settings.twilio_account_sid[:8] if settings.twilio_account_sid else "N/A")
        _twilio_client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    return _twilio_client


async def send_approval_sms(phone_number: str, company_name: str, amount: str, approval_url: str):
    """Send SMS with approval link via Twilio."""
    logger.info("send_approval_sms — to=%s, company=%s, amount=$%s", phone_number, company_name, amount)
    logger.debug("send_approval_sms — approval_url=%s", approval_url)
    logger.debug("send_approval_sms — twilio from=%s, account_sid=%s...",
                 settings.twilio_from_number, settings.twilio_account_sid[:8] if settings.twilio_account_sid else "N/A")

    body = f"3i Fund: ELOC Notice for {company_name} — ${amount}. Tap to approve: {approval_url}"
    logger.debug("send_approval_sms — message body length=%d chars", len(body))

    try:
        client = _get_twilio_client()
        message = await asyncio.to_thread(
            client.messages.create,
            body=body,
            from_=settings.twilio_from_number,
            to=phone_number,
        )
        logger.info("send_approval_sms — SUCCESS: SID=%s, status=%s, to=%s, company=%s",
                     message.sid, message.status, phone_number, company_name)
        return {"sid": message.sid, "status": message.status}
    except Exception as exc:
        logger.error("send_approval_sms — FAILED: to=%s, company=%s, error=%s",
                     phone_number, company_name, exc, exc_info=True)
        raise

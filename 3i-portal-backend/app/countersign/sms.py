"""Twilio SMS sender for Purchase Confirmation countersign notifications."""

import logging
from app.config import settings

logger = logging.getLogger("portal.countersign.sms")

_twilio_client = None


def _get_twilio_client():
    """Get or create a cached Twilio client (reuses HTTP connections)."""
    global _twilio_client
    if _twilio_client is None:
        from twilio.rest import Client
        logger.info("Creating Twilio client (countersign) — account_sid=%s...",
                     settings.twilio_account_sid[:8] if settings.twilio_account_sid else "N/A")
        _twilio_client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    return _twilio_client


async def send_countersign_sms(
    phone_number: str, company_name: str, countersign_url: str
):
    """Send SMS with countersign link via Twilio."""
    logger.info("send_countersign_sms — to=%s, company=%s", phone_number, company_name)
    logger.debug("send_countersign_sms — url=%s", countersign_url)
    logger.debug("send_countersign_sms — twilio from=%s, account_sid=%s...",
                 settings.twilio_from_number,
                 settings.twilio_account_sid[:8] if settings.twilio_account_sid else "N/A")

    body = (
        f"3i Fund: Purchase Confirmation for {company_name} is ready for countersigning. "
        f"Tap to review and sign: {countersign_url}"
    )
    logger.debug("send_countersign_sms — message body length=%d chars", len(body))

    try:
        client = _get_twilio_client()
        message = client.messages.create(
            body=body,
            from_=settings.twilio_from_number,
            to=phone_number,
        )
        logger.info("send_countersign_sms — SUCCESS: SID=%s, status=%s, to=%s, company=%s",
                     message.sid, message.status, phone_number, company_name)
        return {"sid": message.sid, "status": message.status}
    except Exception as exc:
        logger.error("send_countersign_sms — FAILED: to=%s, company=%s, error=%s",
                     phone_number, company_name, exc, exc_info=True)
        raise

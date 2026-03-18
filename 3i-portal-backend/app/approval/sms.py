"""Twilio SMS sender for purchase notice approval notifications."""

import logging
from app.config import settings

logger = logging.getLogger("portal.approval.sms")


async def send_approval_sms(phone_number: str, company_name: str, amount: str, approval_url: str):
    """Send SMS with approval link via Twilio."""
    from twilio.rest import Client

    logger.info(f"Sending approval SMS to {phone_number} for {company_name} ${amount}")

    try:
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        message = client.messages.create(
            body=f"3i Fund: ELOC Notice for {company_name} — ${amount}. Tap to approve: {approval_url}",
            from_=settings.twilio_from_number,
            to=phone_number,
        )
        logger.info(f"SMS sent: SID={message.sid} status={message.status} to={phone_number}")
        return {"sid": message.sid, "status": message.status}
    except Exception as e:
        logger.error(f"SMS send failed to {phone_number}: {e}")
        raise

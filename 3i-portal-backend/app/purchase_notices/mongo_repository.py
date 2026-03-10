"""
3i Fund Portal — MongoDB Repository for Purchase Notice Templates & Signatories
Collections: purchase_notice_templates, user_signatories (in portal_3i DB)
"""

import logging
from bson import ObjectId
from app.database.mongo import get_db

logger = logging.getLogger("portal.purchase_notices.repo")


# ---- Purchase Notice Templates ----

async def get_all_templates() -> list[dict]:
    """Get all purchase notice templates."""
    logger.debug("get_all_templates() — querying purchase_notice_templates collection")
    db = get_db()
    cursor = db.purchase_notice_templates.find({}, {"_id": 0})
    result = await cursor.to_list(length=100)
    logger.debug("get_all_templates() — found %d templates", len(result))
    return result


async def get_template_by_period_type(period_type: str) -> dict | None:
    """Get a template by pricing period type (e.g., 'ThreeDay')."""
    logger.debug("get_template_by_period_type(%s) — querying", period_type)
    db = get_db()
    doc = await db.purchase_notice_templates.find_one(
        {"pricing_period_type": period_type}, {"_id": 0}
    )
    if doc:
        logger.debug("get_template_by_period_type(%s) — found: body_text_len=%d, entity=%s",
                      period_type, len(doc.get("body_text", "")), doc.get("agreed_accepted_entity"))
    else:
        logger.debug("get_template_by_period_type(%s) — not found", period_type)
    return doc


async def upsert_template(period_type: str, body_text: str, agreed_accepted_entity: str) -> dict:
    """Create or update a template for a pricing period type."""
    logger.info("upsert_template(%s) — body_text_len=%d, entity=%s",
                period_type, len(body_text), agreed_accepted_entity)
    db = get_db()
    result = await db.purchase_notice_templates.update_one(
        {"pricing_period_type": period_type},
        {"$set": {
            "pricing_period_type": period_type,
            "body_text": body_text,
            "agreed_accepted_entity": agreed_accepted_entity,
        }},
        upsert=True,
    )
    logger.info("upsert_template(%s) — matched=%d, modified=%d, upserted_id=%s",
                period_type, result.matched_count, result.modified_count, result.upserted_id)
    return await get_template_by_period_type(period_type)


# ---- User Signatories ----

async def get_signatories(user_id: str) -> list[dict]:
    """Get all signatories for a user."""
    logger.debug("get_signatories(%s) — querying user_signatories collection", user_id)
    db = get_db()
    doc = await db.user_signatories.find_one({"user_id": user_id})
    if not doc:
        logger.debug("get_signatories(%s) — no document found, returning []", user_id)
        return []
    signatories = doc.get("signatories", [])
    logger.debug("get_signatories(%s) — found %d signatories", user_id, len(signatories))
    return signatories


async def add_signatory(user_id: str, name: str, title: str, address: str, email: str) -> dict:
    """Add a signatory to a user's list. Returns the created signatory."""
    signatory_id = str(ObjectId())
    logger.info("add_signatory(user=%s) — id=%s, name=%s, title=%s, email=%s",
                user_id, signatory_id, name, title, email)
    db = get_db()
    signatory = {
        "_id": signatory_id,
        "name": name,
        "title": title,
        "address": address,
        "email": email,
    }
    result = await db.user_signatories.update_one(
        {"user_id": user_id},
        {"$push": {"signatories": signatory}},
        upsert=True,
    )
    logger.info("add_signatory(user=%s) — id=%s — matched=%d, modified=%d, upserted_id=%s",
                user_id, signatory_id, result.matched_count, result.modified_count, result.upserted_id)
    return signatory


async def update_signatory(user_id: str, signatory_id: str, updates: dict) -> bool:
    """Update specific fields of a signatory. Returns True if modified."""
    logger.info("update_signatory(user=%s, sig=%s) — updates=%s", user_id, signatory_id, updates)
    db = get_db()
    set_fields = {f"signatories.$.{k}": v for k, v in updates.items() if v is not None}
    if not set_fields:
        logger.warning("update_signatory(user=%s, sig=%s) — no valid fields to set", user_id, signatory_id)
        return False
    logger.debug("update_signatory — $set fields: %s", set_fields)
    result = await db.user_signatories.update_one(
        {"user_id": user_id, "signatories._id": signatory_id},
        {"$set": set_fields},
    )
    modified = result.modified_count > 0
    logger.info("update_signatory(user=%s, sig=%s) — matched=%d, modified=%s",
                user_id, signatory_id, result.matched_count, modified)
    return modified


async def delete_signatory(user_id: str, signatory_id: str) -> bool:
    """Remove a signatory from a user's list. Returns True if modified."""
    logger.info("delete_signatory(user=%s, sig=%s)", user_id, signatory_id)
    db = get_db()
    result = await db.user_signatories.update_one(
        {"user_id": user_id},
        {"$pull": {"signatories": {"_id": signatory_id}}},
    )
    modified = result.modified_count > 0
    logger.info("delete_signatory(user=%s, sig=%s) — matched=%d, modified=%s",
                user_id, signatory_id, result.matched_count, modified)
    return modified

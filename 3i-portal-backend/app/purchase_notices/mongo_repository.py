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
    db = get_db()
    cursor = db.purchase_notice_templates.find({}, {"_id": 0})
    return await cursor.to_list(length=100)


async def get_template_by_period_type(period_type: str) -> dict | None:
    """Get a template by pricing period type (e.g., 'ThreeDay')."""
    db = get_db()
    doc = await db.purchase_notice_templates.find_one(
        {"pricing_period_type": period_type}, {"_id": 0}
    )
    return doc


async def upsert_template(period_type: str, body_text: str, agreed_accepted_entity: str) -> dict:
    """Create or update a template for a pricing period type."""
    db = get_db()
    await db.purchase_notice_templates.update_one(
        {"pricing_period_type": period_type},
        {"$set": {
            "pricing_period_type": period_type,
            "body_text": body_text,
            "agreed_accepted_entity": agreed_accepted_entity,
        }},
        upsert=True,
    )
    logger.info("Upserted template for period_type=%s", period_type)
    return await get_template_by_period_type(period_type)


# ---- User Signatories ----

async def get_signatories(user_id: str) -> list[dict]:
    """Get all signatories for a user."""
    db = get_db()
    doc = await db.user_signatories.find_one({"user_id": user_id})
    if not doc:
        return []
    return doc.get("signatories", [])


async def add_signatory(user_id: str, name: str, title: str, address: str, email: str) -> dict:
    """Add a signatory to a user's list. Returns the created signatory."""
    db = get_db()
    signatory = {
        "_id": str(ObjectId()),
        "name": name,
        "title": title,
        "address": address,
        "email": email,
    }
    await db.user_signatories.update_one(
        {"user_id": user_id},
        {"$push": {"signatories": signatory}},
        upsert=True,
    )
    logger.info("Added signatory for user=%s, id=%s", user_id, signatory["_id"])
    return signatory


async def update_signatory(user_id: str, signatory_id: str, updates: dict) -> bool:
    """Update specific fields of a signatory. Returns True if modified."""
    db = get_db()
    set_fields = {f"signatories.$.{k}": v for k, v in updates.items() if v is not None}
    if not set_fields:
        return False
    result = await db.user_signatories.update_one(
        {"user_id": user_id, "signatories._id": signatory_id},
        {"$set": set_fields},
    )
    return result.modified_count > 0


async def delete_signatory(user_id: str, signatory_id: str) -> bool:
    """Remove a signatory from a user's list. Returns True if modified."""
    db = get_db()
    result = await db.user_signatories.update_one(
        {"user_id": user_id},
        {"$pull": {"signatories": {"_id": signatory_id}}},
    )
    logger.info("Deleted signatory user=%s, id=%s, modified=%s",
                user_id, signatory_id, result.modified_count > 0)
    return result.modified_count > 0

"""
3i Fund Portal — MongoDB Repository for Purchase Notice Templates & Signatories
Collections: purchase_notice_templates, company_signatories (in three_i_fund_portal DB)
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
    result = await cursor.to_list(length=500)
    logger.debug("get_all_templates() — found %d templates", len(result))
    return result


async def get_templates_by_company(company_id: int) -> list[dict]:
    """Get all templates for a specific company."""
    logger.debug("get_templates_by_company(%s) — querying", company_id)
    db = get_db()
    cursor = db.purchase_notice_templates.find({"company_id": company_id}, {"_id": 0})
    result = await cursor.to_list(length=100)
    logger.debug("get_templates_by_company(%s) — found %d templates", company_id, len(result))
    return result


async def get_template_by_period_type(period_type: str, company_id: int | None = None) -> dict | None:
    """Get a template by company and pricing period type.
    Falls back to legacy template (no company_id) if company-specific not found."""
    logger.debug("get_template_by_period_type(%s, company_id=%s) — querying", period_type, company_id)
    db = get_db()

    # Try company-specific template first
    if company_id is not None:
        doc = await db.purchase_notice_templates.find_one(
            {"company_id": company_id, "pricing_period_type": period_type}, {"_id": 0}
        )
        if doc:
            logger.debug("get_template_by_period_type(%s, company_id=%s) — found company-specific",
                          period_type, company_id)
            return doc
        logger.debug("get_template_by_period_type(%s, company_id=%s) — no company-specific, trying legacy",
                      period_type, company_id)

    # Fallback to legacy template (no company_id field)
    doc = await db.purchase_notice_templates.find_one(
        {"pricing_period_type": period_type, "company_id": {"$exists": False}}, {"_id": 0}
    )
    if doc:
        logger.debug("get_template_by_period_type(%s) — found legacy: body_text_len=%d, entity=%s",
                      period_type, len(doc.get("body_text", "")), doc.get("agreed_accepted_entity"))
    else:
        logger.debug("get_template_by_period_type(%s, company_id=%s) — not found", period_type, company_id)
    return doc


async def upsert_template(period_type: str, body_text: str, agreed_accepted_entity: str,
                           company_id: int | None = None) -> dict:
    """Create or update a template for a company and pricing period type."""
    logger.info("upsert_template(company_id=%s, %s) — body_text_len=%d, entity=%s",
                company_id, period_type, len(body_text), agreed_accepted_entity)
    db = get_db()

    query = {"pricing_period_type": period_type}
    set_fields = {
        "pricing_period_type": period_type,
        "body_text": body_text,
        "agreed_accepted_entity": agreed_accepted_entity,
    }
    if company_id is not None:
        query["company_id"] = company_id
        set_fields["company_id"] = company_id

    result = await db.purchase_notice_templates.update_one(
        query,
        {"$set": set_fields},
        upsert=True,
    )
    logger.info("upsert_template(company_id=%s, %s) — matched=%d, modified=%d, upserted_id=%s",
                company_id, period_type, result.matched_count, result.modified_count, result.upserted_id)
    return await get_template_by_period_type(period_type, company_id)


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


async def add_signatory(user_id: str, name: str, title: str, address: str, email: str,
                        signature_image: str | None = None) -> dict:
    """Add a signatory to a user's list. Returns the created signatory."""
    signatory_id = str(ObjectId())
    logger.info("add_signatory(user=%s) — id=%s, name=%s, title=%s, email=%s, has_signature=%s",
                user_id, signatory_id, name, title, email, signature_image is not None)
    db = get_db()
    signatory = {
        "_id": signatory_id,
        "name": name,
        "title": title,
        "address": address,
        "email": email,
    }
    if signature_image:
        signatory["signature_image"] = signature_image
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


# ---- Company Signatories (admin-managed names, client-entered details) ----

async def get_company_signatories(company_id: int) -> list[dict]:
    """Get all signatories for a company."""
    logger.debug("get_company_signatories(%s) — querying company_signatories collection", company_id)
    db = get_db()
    doc = await db.company_signatories.find_one({"company_id": company_id})
    if not doc:
        logger.debug("get_company_signatories(%s) — no document found, returning []", company_id)
        return []
    signatories = doc.get("signatories", [])
    logger.debug("get_company_signatories(%s) — found %d signatories", company_id, len(signatories))
    return signatories


async def add_company_signatory(company_id: int, name: str) -> dict:
    """Add a signatory name to a company's list (admin-only). Returns the created signatory."""
    signatory_id = str(ObjectId())
    logger.info("add_company_signatory(company=%s) — id=%s, name=%s", company_id, signatory_id, name)
    db = get_db()
    signatory = {
        "_id": signatory_id,
        "name": name,
        "title": "",
        "address": "",
        "signature_image": None,
    }
    await db.company_signatories.update_one(
        {"company_id": company_id},
        {"$push": {"signatories": signatory}},
        upsert=True,
    )
    logger.info("add_company_signatory(company=%s) — id=%s added", company_id, signatory_id)
    return signatory


async def update_company_signatory_name(company_id: int, signatory_id: str, name: str) -> bool:
    """Update a signatory's name (admin-only). Returns True if modified."""
    logger.info("update_company_signatory_name(company=%s, sig=%s) — name=%s",
                company_id, signatory_id, name)
    db = get_db()
    result = await db.company_signatories.update_one(
        {"company_id": company_id, "signatories._id": signatory_id},
        {"$set": {"signatories.$.name": name}},
    )
    modified = result.modified_count > 0
    logger.info("update_company_signatory_name(company=%s, sig=%s) — modified=%s",
                company_id, signatory_id, modified)
    return modified


async def delete_company_signatory(company_id: int, signatory_id: str) -> bool:
    """Remove a signatory from a company's list (admin-only). Returns True if modified."""
    logger.info("delete_company_signatory(company=%s, sig=%s)", company_id, signatory_id)
    db = get_db()
    result = await db.company_signatories.update_one(
        {"company_id": company_id},
        {"$pull": {"signatories": {"_id": signatory_id}}},
    )
    modified = result.modified_count > 0
    logger.info("delete_company_signatory(company=%s, sig=%s) — modified=%s",
                company_id, signatory_id, modified)
    return modified


async def update_company_signatory_details(company_id: int, signatory_id: str, updates: dict) -> bool:
    """Update signatory details (title, address, signature_image) — client-entered.
    Returns True if modified."""
    logger.info("update_company_signatory_details(company=%s, sig=%s) — keys=%s",
                company_id, signatory_id, list(updates.keys()))
    db = get_db()
    # Only allow detail fields, not name
    allowed = {"title", "address", "signature_image"}
    set_fields = {f"signatories.$.{k}": v for k, v in updates.items() if k in allowed}
    if not set_fields:
        logger.warning("update_company_signatory_details — no valid fields to set")
        return False
    result = await db.company_signatories.update_one(
        {"company_id": company_id, "signatories._id": signatory_id},
        {"$set": set_fields},
    )
    modified = result.modified_count > 0
    logger.info("update_company_signatory_details(company=%s, sig=%s) — modified=%s",
                company_id, signatory_id, modified)
    return modified


# ---- Verified By ----

async def set_verified_by(eloc_id: str, verified_by: str) -> bool:
    """Set the verified_by field on an eloc_data document in portal_3i."""
    logger.info("set_verified_by — eloc_id=%s, verified_by=%s", eloc_id, verified_by)
    db = get_db()
    result = await db.eloc_data.update_one(
        {"eloc_id": eloc_id},
        {"$set": {"verified_by": verified_by}},
    )
    modified = result.modified_count > 0
    logger.info("set_verified_by — eloc_id=%s, verified_by=%s — matched=%d, modified=%s",
                eloc_id, verified_by, result.matched_count, modified)
    if not modified:
        logger.warning("set_verified_by — eloc_id=%s NOT modified (matched=%d). "
                       "Document may not exist yet or value unchanged.",
                       eloc_id, result.matched_count)
    return modified

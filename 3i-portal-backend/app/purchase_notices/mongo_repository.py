
import logging
from app.database.mongo import get_db

logger = logging.getLogger("portal.purchase_notices.repo")



async def get_all_templates() -> list[dict]:
    logger.debug("get_all_templates() — querying purchase_notice_templates collection")
    db = get_db()
    cursor = db.purchase_notice_templates.find({}, {"_id": 0})
    result = await cursor.to_list(length=500)
    logger.debug("get_all_templates() — found %d templates", len(result))
    return result


async def get_templates_by_company(company_id: int) -> list[dict]:
    logger.debug("get_templates_by_company(%s) — querying", company_id)
    db = get_db()
    cursor = db.purchase_notice_templates.find({"company_id": company_id}, {"_id": 0})
    result = await cursor.to_list(length=100)
    logger.debug("get_templates_by_company(%s) — found %d templates", company_id, len(result))
    return result


async def get_template_by_period_type(period_type: str, company_id: int | None = None) -> dict | None:
    logger.debug("get_template_by_period_type(%s, company_id=%s) — querying", period_type, company_id)
    db = get_db()

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



async def get_all_confirmation_templates() -> list[dict]:
    logger.debug("get_all_confirmation_templates() — querying purchase_confirmation_templates collection")
    db = get_db()
    cursor = db.purchase_confirmation_templates.find({}, {"_id": 0})
    result = await cursor.to_list(length=500)
    logger.debug("get_all_confirmation_templates() — found %d templates", len(result))
    return result


async def get_confirmation_templates_by_company(company_id: int) -> list[dict]:
    logger.debug("get_confirmation_templates_by_company(%s) — querying", company_id)
    db = get_db()
    cursor = db.purchase_confirmation_templates.find({"company_id": company_id}, {"_id": 0})
    result = await cursor.to_list(length=100)
    logger.debug("get_confirmation_templates_by_company(%s) — found %d templates", company_id, len(result))
    return result


async def get_confirmation_template_by_period_type(period_type: str, company_id: int | None = None) -> dict | None:
    logger.debug("get_confirmation_template_by_period_type(%s, company_id=%s) — querying", period_type, company_id)
    db = get_db()

    if company_id is not None:
        doc = await db.purchase_confirmation_templates.find_one(
            {"company_id": company_id, "pricing_period_type": period_type}, {"_id": 0}
        )
        if doc:
            logger.debug("get_confirmation_template_by_period_type(%s, company_id=%s) — found company-specific",
                          period_type, company_id)
            return doc

    doc = await db.purchase_confirmation_templates.find_one(
        {"pricing_period_type": period_type, "company_id": {"$exists": False}}, {"_id": 0}
    )
    if doc:
        logger.debug("get_confirmation_template_by_period_type(%s) — found legacy", period_type)
    else:
        logger.debug("get_confirmation_template_by_period_type(%s, company_id=%s) — not found", period_type, company_id)
    return doc


async def upsert_confirmation_template(period_type: str, body_text: str, agreed_accepted_entity: str,
                                         company_id: int | None = None) -> dict:
    logger.info("upsert_confirmation_template(company_id=%s, %s) — body_text_len=%d, entity=%s",
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

    result = await db.purchase_confirmation_templates.update_one(
        query,
        {"$set": set_fields},
        upsert=True,
    )
    logger.info("upsert_confirmation_template(company_id=%s, %s) — matched=%d, modified=%d, upserted_id=%s",
                company_id, period_type, result.matched_count, result.modified_count, result.upserted_id)
    return await get_confirmation_template_by_period_type(period_type, company_id)



async def get_all_backward_notice_templates() -> list[dict]:
    logger.debug("get_all_backward_notice_templates() — querying purchase_notice_backward_templates collection")
    db = get_db()
    cursor = db.purchase_notice_backward_templates.find({}, {"_id": 0})
    result = await cursor.to_list(length=500)
    logger.debug("get_all_backward_notice_templates() — found %d templates", len(result))
    return result


async def get_backward_notice_templates_by_company(company_id: int) -> list[dict]:
    logger.debug("get_backward_notice_templates_by_company(%s) — querying", company_id)
    db = get_db()
    cursor = db.purchase_notice_backward_templates.find({"company_id": company_id}, {"_id": 0})
    result = await cursor.to_list(length=100)
    logger.debug("get_backward_notice_templates_by_company(%s) — found %d templates", company_id, len(result))
    return result


async def get_backward_notice_template_by_period_type(period_type: str, company_id: int | None = None) -> dict | None:
    logger.debug("get_backward_notice_template_by_period_type(%s, company_id=%s) — querying", period_type, company_id)
    db = get_db()

    if company_id is not None:
        doc = await db.purchase_notice_backward_templates.find_one(
            {"company_id": company_id, "pricing_period_type": period_type}, {"_id": 0}
        )
        if doc:
            logger.debug("get_backward_notice_template_by_period_type(%s, company_id=%s) — found company-specific",
                          period_type, company_id)
            return doc
        logger.debug("get_backward_notice_template_by_period_type(%s, company_id=%s) — no company-specific, trying legacy",
                      period_type, company_id)

    doc = await db.purchase_notice_backward_templates.find_one(
        {"pricing_period_type": period_type, "company_id": {"$exists": False}}, {"_id": 0}
    )
    if doc:
        logger.debug("get_backward_notice_template_by_period_type(%s) — found legacy: body_text_len=%d, entity=%s",
                      period_type, len(doc.get("body_text", "")), doc.get("agreed_accepted_entity"))
    else:
        logger.debug("get_backward_notice_template_by_period_type(%s, company_id=%s) — not found", period_type, company_id)
    return doc


async def upsert_backward_notice_template(period_type: str, body_text: str, agreed_accepted_entity: str,
                                            company_id: int | None = None) -> dict:
    logger.info("upsert_backward_notice_template(company_id=%s, %s) — body_text_len=%d, entity=%s",
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

    result = await db.purchase_notice_backward_templates.update_one(
        query,
        {"$set": set_fields},
        upsert=True,
    )
    logger.info("upsert_backward_notice_template(company_id=%s, %s) — matched=%d, modified=%d, upserted_id=%s",
                company_id, period_type, result.matched_count, result.modified_count, result.upserted_id)
    return await get_backward_notice_template_by_period_type(period_type, company_id)



async def set_verified_by(eloc_id: str, verified_by: str) -> bool:
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

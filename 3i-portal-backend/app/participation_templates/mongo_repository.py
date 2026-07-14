
import logging
import uuid

from app.database.mongo import get_db

logger = logging.getLogger("portal.participation_templates.repo")

TEMPLATES = "participation_templates"
MAPPINGS = "participation_template_mappings"



async def ensure_indexes() -> None:
    logger.info("ensure_indexes — creating participation template/mapping unique indexes")
    db = get_db()
    await db[TEMPLATES].create_index(
        [("company_id", 1), ("document_type", 1), ("name", 1)],
        unique=True, name="uniq_company_doctype_name",
    )
    await db[MAPPINGS].create_index(
        [("company_id", 1), ("pricing_period_type", 1), ("document_type", 1)],
        unique=True, name="uniq_company_period_doctype",
    )
    logger.info("ensure_indexes — participation template/mapping indexes ensured")



async def create_template(name: str, company_id: int, document_type: str,
                          body_text: str, agreed_accepted_entity: str,
                          fields: list[dict], allocation_type: str = "Known") -> dict:
    template_id = uuid.uuid4().hex
    logger.info("create_template — name=%s, company_id=%s, document_type=%s, allocation_type=%s, fields=%d -> template_id=%s",
                name, company_id, document_type, allocation_type, len(fields), template_id)
    db = get_db()
    doc = {
        "template_id": template_id,
        "name": name,
        "company_id": company_id,
        "document_type": document_type,
        "allocation_type": allocation_type,
        "body_text": body_text,
        "agreed_accepted_entity": agreed_accepted_entity,
        "fields": fields,
    }
    await db[TEMPLATES].insert_one(doc)
    logger.info("create_template — inserted template_id=%s", template_id)
    return await get_template(template_id)


async def update_template(template_id: str, name: str, company_id: int, document_type: str,
                          body_text: str, agreed_accepted_entity: str,
                          fields: list[dict], allocation_type: str = "Known") -> dict | None:
    logger.info("update_template — template_id=%s, name=%s, company_id=%s, document_type=%s, allocation_type=%s, fields=%d",
                template_id, name, company_id, document_type, allocation_type, len(fields))
    db = get_db()
    result = await db[TEMPLATES].update_one(
        {"template_id": template_id},
        {"$set": {
            "name": name,
            "company_id": company_id,
            "document_type": document_type,
            "allocation_type": allocation_type,
            "body_text": body_text,
            "agreed_accepted_entity": agreed_accepted_entity,
            "fields": fields,
        }},
    )
    logger.info("update_template — template_id=%s matched=%d modified=%d",
                template_id, result.matched_count, result.modified_count)
    if result.matched_count == 0:
        logger.warning("update_template — template_id=%s NOT FOUND", template_id)
        return None
    return await get_template(template_id)


async def get_template(template_id: str) -> dict | None:
    logger.debug("get_template — template_id=%s", template_id)
    db = get_db()
    doc = await db[TEMPLATES].find_one({"template_id": template_id}, {"_id": 0})
    if doc is None:
        logger.debug("get_template — template_id=%s not found", template_id)
    return doc


async def list_templates(company_id: int | None = None,
                         document_type: str | None = None) -> list[dict]:
    query: dict = {}
    if company_id is not None:
        query["company_id"] = company_id
    if document_type is not None:
        query["document_type"] = document_type
    logger.info("list_templates — query=%s", query)
    db = get_db()
    cursor = db[TEMPLATES].find(query, {"_id": 0})
    result = await cursor.to_list(length=500)
    logger.info("list_templates — query=%s returned %d", query, len(result))
    return result


async def delete_template(template_id: str) -> bool:
    logger.info("delete_template — template_id=%s", template_id)
    db = get_db()
    result = await db[TEMPLATES].delete_one({"template_id": template_id})
    deleted = result.deleted_count > 0
    logger.info("delete_template — template_id=%s deleted=%s", template_id, deleted)
    return deleted


async def name_exists(company_id: int, document_type: str, name: str,
                      exclude_template_id: str | None = None) -> bool:
    query: dict = {"company_id": company_id, "document_type": document_type, "name": name}
    if exclude_template_id is not None:
        query["template_id"] = {"$ne": exclude_template_id}
    db = get_db()
    doc = await db[TEMPLATES].find_one(query, {"_id": 0, "template_id": 1})
    exists = doc is not None
    logger.debug("name_exists — company_id=%s, document_type=%s, name=%s, exclude=%s -> %s",
                 company_id, document_type, name, exclude_template_id, exists)
    return exists



async def upsert_mapping(company_id: int, pricing_period_type: str,
                         document_type: str, template_id: str) -> dict | None:
    logger.info("upsert_mapping — company_id=%s, pricing_period_type=%s, document_type=%s, template_id=%s",
                company_id, pricing_period_type, document_type, template_id)
    db = get_db()
    key = {"company_id": company_id, "pricing_period_type": pricing_period_type,
           "document_type": document_type}
    result = await db[MAPPINGS].update_one(key, {"$set": {**key, "template_id": template_id}}, upsert=True)
    logger.info("upsert_mapping — matched=%d modified=%d upserted_id=%s",
                result.matched_count, result.modified_count, result.upserted_id)
    return await get_mapping(company_id, pricing_period_type, document_type)


async def get_mapping(company_id: int, pricing_period_type: str,
                      document_type: str) -> dict | None:
    logger.debug("get_mapping — company_id=%s, pricing_period_type=%s, document_type=%s",
                 company_id, pricing_period_type, document_type)
    db = get_db()
    return await db[MAPPINGS].find_one(
        {"company_id": company_id, "pricing_period_type": pricing_period_type,
         "document_type": document_type},
        {"_id": 0},
    )


async def list_mappings(company_id: int | None = None,
                        document_type: str | None = None) -> list[dict]:
    query: dict = {}
    if company_id is not None:
        query["company_id"] = company_id
    if document_type is not None:
        query["document_type"] = document_type
    logger.info("list_mappings — query=%s", query)
    db = get_db()
    cursor = db[MAPPINGS].find(query, {"_id": 0})
    result = await cursor.to_list(length=500)
    logger.info("list_mappings — query=%s returned %d", query, len(result))
    return result


async def list_mappings_for_template(template_id: str) -> list[dict]:
    logger.debug("list_mappings_for_template — template_id=%s", template_id)
    db = get_db()
    cursor = db[MAPPINGS].find({"template_id": template_id}, {"_id": 0})
    result = await cursor.to_list(length=500)
    logger.info("list_mappings_for_template — template_id=%s returned %d", template_id, len(result))
    return result


async def delete_mapping(company_id: int, pricing_period_type: str,
                         document_type: str) -> bool:
    logger.info("delete_mapping — company_id=%s, pricing_period_type=%s, document_type=%s",
                company_id, pricing_period_type, document_type)
    db = get_db()
    result = await db[MAPPINGS].delete_one(
        {"company_id": company_id, "pricing_period_type": pricing_period_type,
         "document_type": document_type})
    deleted = result.deleted_count > 0
    logger.info("delete_mapping — deleted=%s", deleted)
    return deleted


async def resolve(company_id: int, pricing_period_type: str,
                  document_type: str) -> dict | None:
    logger.info("resolve — company_id=%s, pricing_period_type=%s, document_type=%s",
                company_id, pricing_period_type, document_type)
    mapping = await get_mapping(company_id, pricing_period_type, document_type)
    if mapping is None:
        logger.warning("resolve — NO MAPPING for company_id=%s, pricing_period_type=%s, document_type=%s",
                       company_id, pricing_period_type, document_type)
        return None
    template = await get_template(mapping["template_id"])
    if template is None:
        logger.warning("resolve — mapping points to MISSING template_id=%s", mapping["template_id"])
        return None
    logger.info("resolve — resolved to template_id=%s (name=%s)",
                template["template_id"], template.get("name"))
    return template

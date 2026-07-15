
import logging

from app.database.mongo import get_db

logger = logging.getLogger("portal.conversion_notice.repo")

TEMPLATES = "conversion_notice_templates"
MAPPINGS = "conversion_notice_mappings"

# Fixed, seeded conversion-notice template extracted from the ZBAO Acceleration Conversion Notice.
# Title section (text + font size), body text (through "...meaning as set forth in the Note"), then the
# field rows (label + type). Not editable in the UI — the tab only lists/previews/maps these.
_ZBAO_TEMPLATE_1 = {
    "template_id": "zbao-conv-template-1",
    "name": "ZBAO-CONV-Template-1",
    "title_lines": ["ZHIBAO TECHNOLOGY INC.", "CONVERSION NOTICE"],
    "title_font_size": "Large",
    "body_text": (
        "Reference is made to the Convertible Note (the “Note”) issued to the undersigned by "
        "Zhibao Technology Inc., a Cayman Island exempted company (the “Company”). In accordance "
        "with and pursuant to the Note, the undersigned hereby elects to convert the Conversion Amount "
        "(as defined in the Note) of the Note indicated below into Class A ordinary shares, $0.001 par "
        "value per share (the “Ordinary Shares”), of the Company, as of the date specified below. "
        "Capitalized terms not defined herein shall have the meaning as set forth in the Note."
    ),
    "fields": [
        {"order": 1, "type": "data", "label": "Date of Conversion:"},
        {"order": 2, "type": "data", "label": "Aggregate Principal to be converted:"},
        {"order": 3, "type": "data", "label": "Aggregate accrued and unpaid Interest (including Default Interest, if applicable), Make-Whole Amount and accrued and unpaid Late Charges with respect to such portion of the Aggregate Principal and such Aggregate Interest and Aggregate Make-Whole Amount to be converted:"},
        {"order": 4, "type": "data", "label": "Aggregate Conversion Amount to be Converted:"},
        {"order": 5, "type": "section", "label": "Please confirm the following information:"},
        {"order": 6, "type": "data", "label": "Acceleration Conversion Price:"},
        {"order": 7, "type": "data", "label": "Number of Ordinary Shares to be issued:"},
        {"order": 8, "type": "data", "label": "Less: Number of Pre-Delivery Shares held by Holder to be applied against Ordinary Shares otherwise required to be issued:"},
        {"order": 9, "type": "data", "label": "Number of Ordinary Shares to be issued (after reduction for such Pre-Delivery Shares):"},
        {"order": 10, "type": "instruction", "label": "Please issue the Ordinary Shares into which the Note is being converted to Holder, or for its benefit, as follows:"},
        {"order": 11, "type": "checkbox", "label": "Check here if requesting delivery as a certificate to the following name and to the following address:"},
        {"order": 12, "type": "data", "label": "Issue to:"},
        {"order": 13, "type": "checkbox", "label": "Check here if requesting delivery by Deposit/Withdrawal at Custodian as follows:"},
        {"order": 14, "type": "data", "label": "DTC Participant:"},
        {"order": 15, "type": "data", "label": "DTC Number:"},
        {"order": 16, "type": "data", "label": "Account Number:"},
        {"order": 17, "type": "data", "label": "Date:"},
        {"order": 18, "type": "signature", "label": "By:"},
        {"order": 19, "type": "signature", "label": "By:"},
        {"order": 20, "type": "data", "label": "Name:"},
        {"order": 21, "type": "data", "label": "Title:"},
        {"order": 22, "type": "data", "label": "Tax ID:"},
        {"order": 23, "type": "data", "label": "E-Mail Address:"},
        {"order": 24, "type": "data", "label": "Remaining Principal Post Conversion:"},
        {"order": 25, "type": "data", "label": "Remaining Interest & Make Whole Post Conversion:"},
    ],
}


async def ensure_indexes() -> None:
    logger.info("ensure_indexes — conversion-notice template/mapping indexes + seed")
    db = get_db()
    await db[TEMPLATES].create_index("template_id", unique=True, name="uniq_template_id")
    await db[TEMPLATES].create_index("name", unique=True, name="uniq_name")
    await db[MAPPINGS].create_index("instrument_id", unique=True, name="uniq_instrument_id")
    await _seed_default_templates(db)
    logger.info("ensure_indexes — conversion-notice indexes ensured")


async def _seed_default_templates(db) -> None:
    existing = await db[TEMPLATES].find_one({"template_id": _ZBAO_TEMPLATE_1["template_id"]}, {"_id": 0})
    if existing is None:
        await db[TEMPLATES].insert_one(dict(_ZBAO_TEMPLATE_1))
        logger.info("seeded conversion-notice template %s", _ZBAO_TEMPLATE_1["name"])


async def list_templates() -> list[dict]:
    db = get_db()
    cursor = db[TEMPLATES].find({}, {"_id": 0}).sort("name", 1)
    return [doc async for doc in cursor]


async def get_template(template_id: str) -> dict | None:
    db = get_db()
    return await db[TEMPLATES].find_one({"template_id": template_id}, {"_id": 0})


async def list_mappings() -> list[dict]:
    db = get_db()
    cursor = db[MAPPINGS].find({}, {"_id": 0})
    return [doc async for doc in cursor]


async def upsert_mapping(instrument_id: int, template_id: str) -> None:
    db = get_db()
    await db[MAPPINGS].update_one(
        {"instrument_id": instrument_id},
        {"$set": {"instrument_id": instrument_id, "template_id": template_id}},
        upsert=True,
    )
    logger.info("mapped instrument %s -> template %s", instrument_id, template_id)


async def delete_mapping(instrument_id: int) -> bool:
    db = get_db()
    result = await db[MAPPINGS].delete_one({"instrument_id": instrument_id})
    logger.info("unmapped instrument %s (deleted=%s)", instrument_id, result.deleted_count)
    return result.deleted_count > 0

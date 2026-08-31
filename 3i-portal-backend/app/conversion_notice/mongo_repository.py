
import logging

from app.database.mongo import get_db

logger = logging.getLogger("portal.conversion_notice.repo")

TEMPLATES = "conversion_notice_templates"
MAPPINGS = "conversion_notice_mappings"

KIND_NOTICE = "conversion_notice"
KIND_DETAILS = "conversion_details"
KIND_PREFERRED = "preferred_conversion_notice"
KIND_EOD = "eod_default"

# Fixed, seeded templates. Each carries a `kind` so the same collections/UI serve both the Conversion
# Notice tab and the Conversion Details tab. Not editable in the UI — the tabs only list/preview/map them.
_TEMPLATES = [
    {
        "template_id": "zbao-conv-template-1",
        "kind": KIND_NOTICE,
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
            {"order": 6, "type": "data", "label": "Conversion Type:"},
            {"order": 7, "type": "data", "label": "Conversion Price:"},
            {"order": 8, "type": "data", "label": "Number of Ordinary Shares to be issued:"},
            {"order": 9, "type": "data", "label": "Less: Number of Pre-Delivery Shares held by Holder to be applied against Ordinary Shares otherwise required to be issued:"},
            {"order": 10, "type": "data", "label": "Number of Ordinary Shares to be issued (after reduction for such Pre-Delivery Shares):"},
            {"order": 11, "type": "instruction", "label": "Please issue the Ordinary Shares into which the Note is being converted to Holder, or for its benefit, as follows:"},
            {"order": 12, "type": "checkbox", "label": "Check here if requesting delivery as a certificate to the following name and to the following address:"},
            {"order": 13, "type": "data", "label": "Issue to:"},
            {"order": 14, "type": "checkbox", "label": "Check here if requesting delivery by Deposit/Withdrawal at Custodian as follows:"},
            {"order": 15, "type": "data", "label": "DTC Participant:"},
            {"order": 16, "type": "data", "label": "DTC Number:"},
            {"order": 17, "type": "data", "label": "Account Number:"},
            {"order": 18, "type": "data", "label": "Date:"},
            {"order": 19, "type": "signature", "label": "By:"},
            {"order": 20, "type": "signature", "label": "By:"},
            {"order": 21, "type": "data", "label": "Name:"},
            {"order": 22, "type": "data", "label": "Title:"},
            {"order": 23, "type": "data", "label": "Tax ID:"},
            {"order": 24, "type": "data", "label": "E-Mail Address:"},
        ],
    },
    {
        "template_id": "zbao-conv-details-template-1",
        "kind": KIND_DETAILS,
        "name": "ZBAO-CONV-Details-Template-1",
        "title_lines": ["CONVERSION DETAILS"],
        "title_font_size": "Normal",
        "body_text": "",
        "fields": [
            {"order": 1, "type": "data", "label": "Aggregate Interest Converting"},
            {"order": 2, "type": "data", "label": "Accrued Interest"},
            {"order": 3, "type": "data", "label": "Make-Whole"},
            {"order": 4, "type": "data", "label": "Remaining Principal Post Conversion:"},
            {"order": 5, "type": "data", "label": "Remaining Interest & Make Whole Post Conversion:"},
        ],
    },
    {
        # Preferred Notice of Conversion (Annex A). {{Series}} / {{SeriesUpper}} / {{Company}} tokens are substituted
        # per-conversion by DTS (PreferredConversionNoticeService) so one template serves every series.
        "template_id": "vbio-pref-conv-notice-1",
        "kind": KIND_PREFERRED,
        "name": "VBIO-PREF-CONV-Notice-1",
        "title_lines": ["ANNEX A", "NOTICE OF CONVERSION"],
        "title_font_size": "Large",
        "body_text": (
            "(TO BE EXECUTED BY THE REGISTERED HOLDER IN ORDER TO CONVERT SHARES OF {{SeriesUpper}} NON-VOTING "
            "CONVERTIBLE PREFERRED STOCK)\n\n"
            "Reference is made to the Certificate of Designation of the Certificate of Incorporation of {{Company}}, "
            "a Delaware corporation (the \"Corporation\") establishing the terms, preferences and rights of the "
            "{{Series}} Non-Voting Convertible Preferred Stock, $0.0001 par value (the \"{{Series}} Preferred Stock\") "
            "of the Corporation (the \"Certificate of Designation\"). In accordance with and pursuant to the Certificate "
            "of Designation, the undersigned hereby elects to convert the number of shares of {{Series}} Preferred Stock "
            "indicated below into shares of common stock, $0.0001 value per share (the \"Common Stock\"), of the "
            "Corporation, as of the date specified below."
        ),
        "fields": [
            {"order": 0, "type": "data", "label": "Date of Conversion:"},
            {"order": 1, "type": "data", "label": "Aggregate number of shares of {{Series}} Preferred Stock to be converted:"},
            {"order": 2, "type": "data", "label": "Aggregate Stated Value of such shares of {{Series}} Preferred Stock to be converted:"},
            {"order": 3, "type": "data", "label": "Aggregate accrued and unpaid Dividends with respect to such shares of {{Series}} Preferred Stock to be converted:"},
            {"order": 4, "type": "data", "label": "AGGREGATE CONVERSION AMOUNT TO BE CONVERTED:"},
            {"order": 5, "type": "section", "label": "Please confirm the following information:"},
            {"order": 6, "type": "data", "label": "Conversion Price:"},
            {"order": 7, "type": "data", "label": "Number of shares of Common Stock to be issued:"},
            {"order": 8, "type": "instruction", "label": "Please issue the Common Stock into which the applicable shares of {{Series}} Preferred Stock are being converted to Holder, or for its benefit, as follows:"},
            {"order": 9, "type": "checkbox", "label": "Check here if requesting delivery as a certificate to the following name and to the following address:"},
            {"order": 10, "type": "data", "label": "Issue to:"},
            {"order": 11, "type": "checkbox", "label": "Check here if requesting delivery by Deposit/Withdrawal at Custodian as follows:"},
            {"order": 12, "type": "data", "label": "DTC Participant:"},
            {"order": 13, "type": "data", "label": "DTC Number:"},
            {"order": 14, "type": "data", "label": "Account Number:"},
            {"order": 15, "type": "signature", "label": "By:"},
            {"order": 16, "type": "signature", "label": "By:"},
            {"order": 17, "type": "data", "label": "Name:"},
            {"order": 18, "type": "data", "label": "Title:"},
            {"order": 19, "type": "data", "label": "{{Series}} Non-Voting Convertible Preferred Stock Remaining Post Conversion:"},
        ],
    },
    {
        # BGL (Blue Gold Limited) convertible note Conversion Notice. The note's issuance date renders under the
        # title (populated by DTS from the note) — no top-of-page issuance-date header.
        "template_id": "bgl-conv-template-1",
        "kind": KIND_NOTICE,
        "name": "BGL-CONV-Template-1",
        "title_lines": ["BLUE GOLD LIMITED", "CONVERSION NOTICE"],
        "title_font_size": "Large",
        "body_text": (
            "Reference is made to the Convertible Note (the \"Note\") issued to the undersigned by Blue Gold Limited, "
            "a Cayman Islands exempted company (the \"Company\"). In accordance with and pursuant to the Note, the "
            "undersigned hereby elects to convert the Conversion Amount (as defined in the Note) of the Note indicated "
            "below into Ordinary Shares, $0.0001 par value per share (the \"Ordinary Shares\"), of the Company, as of "
            "the date specified below. Capitalized terms not defined herein shall have the meaning as set forth in the Note."
        ),
        "fields": [
            {"order": 0, "type": "data", "label": "Date of Conversion:"},
            {"order": 1, "type": "data", "label": "Aggregate Principal to be converted:"},
            {"order": 2, "type": "data", "label": "Aggregate accrued and unpaid Interest (including Default Interest, if applicable), Make-Whole Amount and accrued and unpaid Late Charges with respect to such portion of the Aggregate Principal and such Aggregate Interest and Aggregate Make-Whole Amount to be converted:"},
            {"order": 3, "type": "data", "label": "Aggregate Conversion Amount to be Converted:"},
            {"order": 4, "type": "section", "label": "Please confirm the following information:"},
            {"order": 5, "type": "data", "label": "Conversion Price:"},
            {"order": 6, "type": "data", "label": "Number of Ordinary Shares to be issued:"},
            {"order": 7, "type": "data", "label": "Less: Number of Pre-Delivery Shares held by Holder to be applied against Ordinary Shares otherwise required to be issued:"},
            {"order": 8, "type": "data", "label": "Number of Ordinary Shares to be issued (after reduction for such Pre-Delivery Shares):"},
            {"order": 9, "type": "instruction", "label": "Please issue the Ordinary Shares into which the Note is being converted to Holder, or for its benefit, as follows:"},
            {"order": 10, "type": "checkbox", "label": "Check here if requesting delivery as a certificate to the following name and to the following address:"},
            {"order": 11, "type": "data", "label": "Issue to:"},
            {"order": 12, "type": "checkbox", "label": "Check here if requesting delivery by Deposit/Withdrawal at Custodian as follows:"},
            {"order": 13, "type": "data", "label": "DTC Participant:"},
            {"order": 14, "type": "data", "label": "DTC Number:"},
            {"order": 15, "type": "data", "label": "Account Number:"},
            {"order": 16, "type": "data", "label": "Date:"},
            {"order": 17, "type": "signature", "label": "By:"},
            {"order": 18, "type": "signature", "label": "By:"},
            {"order": 19, "type": "data", "label": "Name:"},
            {"order": 20, "type": "data", "label": "Title:"},
            {"order": 21, "type": "data", "label": "Tax ID:"},
            {"order": 22, "type": "data", "label": "E-Mail Address:"},
            {"order": 23, "type": "data", "label": "Remaining Principal Post Conversion:"},
            {"order": 24, "type": "data", "label": "Remaining Interest & Make Whole Post Conversion:"},
        ],
    },
    {
        # Event of Default Redemption Notice (BGL). A narrative notice that precedes the Conversion Notice(s) when a
        # note is in default; {{Company}} / {{IssuanceDate}} are substituted per-note by DTS. No form fields.
        "template_id": "bgl-default-template-1",
        "kind": KIND_EOD,
        "name": "BGL-DEFAULT-Template-1",
        "title_lines": ["{{Company}}"],
        "title_font_size": "Large",
        "body_text": (
            "This notice is provided by 3i, LP (the \"Holder\") pursuant to the Senior Convertible Note (the \"Note\") "
            "issued by {{Company}} to 3i, LP with an Issuance Date of {{IssuanceDate}}. Notice is hereby given that one "
            "or more Events of Default have occurred under the Note and the Holder is hereby providing an Event of "
            "Default Redemption Notice electing to convert a portion of this Note as detailed in the subsequent "
            "Conversion Notice(s). 3i, LP reserves all rights."
        ),
        "fields": [],
    },
]


async def ensure_indexes() -> None:
    logger.info("ensure_indexes — conversion-notice/details template + mapping indexes + seed")
    db = get_db()
    for old, coll in (("uniq_name", TEMPLATES), ("uniq_instrument_id", MAPPINGS)):
        try:
            await db[coll].drop_index(old)
        except Exception:
            pass
    await db[TEMPLATES].create_index("template_id", unique=True, name="uniq_template_id")
    await db[TEMPLATES].create_index([("kind", 1), ("name", 1)], unique=True, name="uniq_kind_name")
    backfilled = await db[MAPPINGS].update_many({"kind": {"$exists": False}}, {"$set": {"kind": KIND_NOTICE}})
    if backfilled.modified_count:
        logger.info("backfilled %s pre-kind mapping(s) to %s", backfilled.modified_count, KIND_NOTICE)
    await db[MAPPINGS].create_index([("instrument_id", 1), ("kind", 1)], unique=True, name="uniq_instrument_kind")
    await _seed_default_templates(db)
    logger.info("ensure_indexes — conversion-notice/details indexes ensured")


async def _seed_default_templates(db) -> None:
    for tpl in _TEMPLATES:
        existing = await db[TEMPLATES].find_one({"template_id": tpl["template_id"]}, {"_id": 0})
        if existing is None:
            await db[TEMPLATES].insert_one(dict(tpl))
            logger.info("seeded template %s (%s)", tpl["name"], tpl["kind"])
        elif existing.get("fields") != tpl["fields"] or existing.get("kind") != tpl["kind"]:
            await db[TEMPLATES].update_one({"template_id": tpl["template_id"]}, {"$set": dict(tpl)})
            logger.info("refreshed seeded template %s (%s)", tpl["name"], tpl["kind"])


async def list_templates(kind: str) -> list[dict]:
    db = get_db()
    cursor = db[TEMPLATES].find({"kind": kind}, {"_id": 0}).sort("name", 1)
    return [doc async for doc in cursor]


async def get_template(template_id: str) -> dict | None:
    db = get_db()
    return await db[TEMPLATES].find_one({"template_id": template_id}, {"_id": 0})


async def list_mappings(kind: str) -> list[dict]:
    db = get_db()
    cursor = db[MAPPINGS].find({"kind": kind}, {"_id": 0})
    return [doc async for doc in cursor]


async def upsert_mapping(instrument_id: int, template_id: str, kind: str) -> None:
    db = get_db()
    await db[MAPPINGS].update_one(
        {"instrument_id": instrument_id, "kind": kind},
        {"$set": {"instrument_id": instrument_id, "kind": kind, "template_id": template_id}},
        upsert=True,
    )
    logger.info("mapped instrument %s (%s) -> template %s", instrument_id, kind, template_id)


async def delete_mapping(instrument_id: int, kind: str) -> bool:
    db = get_db()
    result = await db[MAPPINGS].delete_one({"instrument_id": instrument_id, "kind": kind})
    logger.info("unmapped instrument %s (%s) (deleted=%s)", instrument_id, kind, result.deleted_count)
    return result.deleted_count > 0

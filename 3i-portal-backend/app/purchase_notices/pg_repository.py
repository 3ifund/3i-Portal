"""
3i Fund Portal — Company Signatories PostgreSQL Repository
Manages company_signatories table in PostgreSQL (DealTerms DB).
Migrated from MongoDB three_i_fund_portal.company_signatories collection.
"""

import base64
import logging

from app.database.postgres import get_pool

logger = logging.getLogger("portal.signatories")


# ---- Table Creation ----

async def ensure_company_signatories_table() -> None:
    """Create the company_signatories table if it doesn't exist."""
    pool = get_pool()

    await pool.execute("""
        CREATE TABLE IF NOT EXISTS company_signatories (
            id              SERIAL          PRIMARY KEY,
            company_id      INTEGER         NOT NULL REFERENCES company(company_id),
            name            VARCHAR(255)    NOT NULL,
            title           VARCHAR(255)    NOT NULL DEFAULT '',
            address         TEXT            NOT NULL DEFAULT '',
            phone_number    VARCHAR(50)     NOT NULL DEFAULT '',
            signature_image BYTEA           NULL,
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            modified_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        )
    """)
    logger.info("company_signatories table ensured")


# ---- Helpers ----

def _row_to_dict(row) -> dict:
    """Convert an asyncpg Record to a dict with base64-encoded signature_image."""
    d = dict(row)
    # Convert bytea to base64 data URI for frontend consumption
    if d.get("signature_image"):
        b64 = base64.b64encode(d["signature_image"]).decode("ascii")
        d["signature_image"] = f"data:image/png;base64,{b64}"
    else:
        d["signature_image"] = None
    return d


def _decode_signature(signature_image_b64: str | None) -> bytes | None:
    """Decode a base64 data URI to raw bytes for bytea storage."""
    if not signature_image_b64:
        return None
    # Strip data URI prefix if present
    if "," in signature_image_b64:
        signature_image_b64 = signature_image_b64.split(",", 1)[1]
    return base64.b64decode(signature_image_b64)


# ---- CRUD ----

async def get_company_signatories(company_id: int) -> list[dict]:
    """Get all signatories for a company."""
    logger.debug("get_company_signatories(%s) — querying company_signatories table", company_id)
    pool = get_pool()
    rows = await pool.fetch(
        """SELECT id, company_id, name, title, address, phone_number, signature_image,
                  created_at, modified_at
           FROM company_signatories
           WHERE company_id = $1
           ORDER BY id""",
        company_id,
    )
    signatories = [_row_to_dict(r) for r in rows]
    logger.debug("get_company_signatories(%s) — returned %d signatories", company_id, len(signatories))
    return signatories


async def add_company_signatory(company_id: int, name: str) -> dict:
    """Add a signatory name to a company (admin-only). Returns the created signatory."""
    logger.info("add_company_signatory(company=%s, name=%s)", company_id, name)
    pool = get_pool()
    row = await pool.fetchrow(
        """INSERT INTO company_signatories (company_id, name)
           VALUES ($1, $2)
           RETURNING id, company_id, name, title, address, phone_number, signature_image,
                     created_at, modified_at""",
        company_id, name,
    )
    signatory = _row_to_dict(row)
    logger.info("add_company_signatory(company=%s) — created id=%s, name=%s",
                company_id, signatory["id"], signatory["name"])
    return signatory


async def update_company_signatory_name(company_id: int, signatory_id: int, name: str) -> bool:
    """Update a signatory's name (admin-only). Returns True if modified."""
    logger.info("update_company_signatory_name(company=%s, sig=%s, name=%s)",
                company_id, signatory_id, name)
    pool = get_pool()
    result = await pool.execute(
        """UPDATE company_signatories
           SET name = $1, modified_at = NOW()
           WHERE id = $2 AND company_id = $3""",
        name, signatory_id, company_id,
    )
    ok = result == "UPDATE 1"
    logger.info("update_company_signatory_name(company=%s, sig=%s) — result=%s, ok=%s",
                company_id, signatory_id, result, ok)
    return ok


async def delete_company_signatory(company_id: int, signatory_id: int) -> bool:
    """Remove a signatory from a company (admin-only). Returns True if deleted."""
    logger.info("delete_company_signatory(company=%s, sig=%s)", company_id, signatory_id)
    pool = get_pool()
    result = await pool.execute(
        "DELETE FROM company_signatories WHERE id = $1 AND company_id = $2",
        signatory_id, company_id,
    )
    ok = result == "DELETE 1"
    logger.info("delete_company_signatory(company=%s, sig=%s) — result=%s, ok=%s",
                company_id, signatory_id, result, ok)
    return ok


async def update_company_signatory_details(
    company_id: int, signatory_id: int, updates: dict
) -> bool:
    """Update signatory details (title, address, phone_number, signature_image) — client-entered.
    Returns True if modified."""
    logger.info("update_company_signatory_details(company=%s, sig=%s) — keys=%s",
                company_id, signatory_id, list(updates.keys()))

    # Only allow detail fields, not name
    allowed = {"title", "address", "phone_number", "signature_image"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        logger.warning("update_company_signatory_details — no valid fields to set")
        return False

    # Build dynamic SET clause
    set_parts = []
    params = []
    param_idx = 1

    for key, value in filtered.items():
        if key == "signature_image":
            # Convert base64 to bytes for bytea storage
            set_parts.append(f"signature_image = ${param_idx}")
            params.append(_decode_signature(value))
        else:
            set_parts.append(f"{key} = ${param_idx}")
            params.append(value)
        param_idx += 1

    set_parts.append(f"modified_at = NOW()")
    set_clause = ", ".join(set_parts)

    # Add WHERE params
    params.append(signatory_id)
    params.append(company_id)

    sql = f"UPDATE company_signatories SET {set_clause} WHERE id = ${param_idx} AND company_id = ${param_idx + 1}"

    pool = get_pool()
    result = await pool.execute(sql, *params)
    ok = result == "UPDATE 1"
    logger.info("update_company_signatory_details(company=%s, sig=%s) — result=%s, ok=%s",
                company_id, signatory_id, result, ok)
    return ok

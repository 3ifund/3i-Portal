"""
3i Fund Portal — Approval Repository
Manages approval_contacts, company_verification_settings, and approval_tokens
tables in PostgreSQL (DealTerms DB).
"""

import logging

from app.database.postgres import get_pool

logger = logging.getLogger("portal.approval")


# ---- Table Creation ----

async def ensure_approval_tables() -> None:
    """Create approval-related tables if they don't exist."""
    pool = get_pool()

    await pool.execute("""
        CREATE TABLE IF NOT EXISTS approval_contacts (
            id              SERIAL          PRIMARY KEY,
            name            VARCHAR(255)    NOT NULL,
            phone_number    VARCHAR(50)     NOT NULL,
            include         BOOLEAN         NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        )
    """)
    logger.info("approval_contacts table ensured")

    await pool.execute("""
        CREATE TABLE IF NOT EXISTS company_verification_settings (
            company_id              INTEGER     PRIMARY KEY REFERENCES company(company_id),
            require_verification    BOOLEAN     NOT NULL DEFAULT FALSE,
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    logger.info("company_verification_settings table ensured")

    await pool.execute("""
        CREATE TABLE IF NOT EXISTS approval_tokens (
            token           VARCHAR(255)    PRIMARY KEY,
            group_id        VARCHAR(255)    NOT NULL,
            contact_name    VARCHAR(255)    NOT NULL,
            contact_phone   VARCHAR(50)     NOT NULL,
            company_name    VARCHAR(255)    NOT NULL,
            amount          VARCHAR(50)     NOT NULL,
            status          VARCHAR(20)     NOT NULL DEFAULT 'pending',
            eloc_id         VARCHAR(255)    NULL,
            payload_json    TEXT            NULL,
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            expires_at      TIMESTAMPTZ     NOT NULL,
            responded_at    TIMESTAMPTZ     NULL
        )
    """)

    # Migration: add eloc_id column and make payload_json nullable for existing tables
    await pool.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'approval_tokens' AND column_name = 'eloc_id'
            ) THEN
                ALTER TABLE approval_tokens ADD COLUMN eloc_id VARCHAR(255) NULL;
            END IF;
        END $$;
    """)
    await pool.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'approval_tokens' AND column_name = 'payload_json'
            ) THEN
                ALTER TABLE approval_tokens ALTER COLUMN payload_json DROP NOT NULL;
            END IF;
        END $$;
    """)
    logger.info("approval_tokens table ensured (with eloc_id column)")


# ---- Approval Contacts CRUD ----

async def get_approval_contacts() -> list[dict]:
    logger.debug("get_approval_contacts() — querying all contacts")
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, name, phone_number, include, created_at FROM approval_contacts ORDER BY id"
    )
    contacts = [dict(r) for r in rows]
    logger.debug("get_approval_contacts() — returned %d contacts", len(contacts))
    return contacts


async def create_approval_contact(name: str, phone_number: str) -> dict:
    logger.info("create_approval_contact(name=%s, phone=%s)", name, phone_number)
    pool = get_pool()
    row = await pool.fetchrow(
        "INSERT INTO approval_contacts (name, phone_number) VALUES ($1, $2) RETURNING id, name, phone_number, include, created_at",
        name, phone_number,
    )
    contact = dict(row)
    logger.info("create_approval_contact — created id=%s, name=%s, phone=%s",
                contact["id"], contact["name"], contact["phone_number"])
    return contact


async def update_approval_contact(contact_id: int, name: str, phone_number: str) -> bool:
    logger.info("update_approval_contact(id=%d, name=%s, phone=%s)", contact_id, name, phone_number)
    pool = get_pool()
    result = await pool.execute(
        "UPDATE approval_contacts SET name = $1, phone_number = $2 WHERE id = $3",
        name, phone_number, contact_id,
    )
    ok = result == "UPDATE 1"
    logger.info("update_approval_contact(id=%d) — result=%s, ok=%s", contact_id, result, ok)
    return ok


async def delete_approval_contact(contact_id: int) -> bool:
    logger.info("delete_approval_contact(id=%d)", contact_id)
    pool = get_pool()
    result = await pool.execute(
        "DELETE FROM approval_contacts WHERE id = $1", contact_id,
    )
    ok = result == "DELETE 1"
    logger.info("delete_approval_contact(id=%d) — result=%s, ok=%s", contact_id, result, ok)
    return ok


async def set_contact_include(contact_id: int, include: bool) -> bool:
    logger.info("set_contact_include(id=%d, include=%s)", contact_id, include)
    pool = get_pool()
    result = await pool.execute(
        "UPDATE approval_contacts SET include = $1 WHERE id = $2",
        include, contact_id,
    )
    ok = result == "UPDATE 1"
    logger.info("set_contact_include(id=%d, include=%s) — result=%s, ok=%s",
                contact_id, include, result, ok)
    return ok


async def get_included_contacts() -> list[dict]:
    logger.debug("get_included_contacts() — querying contacts where include=TRUE")
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, name, phone_number FROM approval_contacts WHERE include = TRUE ORDER BY id"
    )
    contacts = [dict(r) for r in rows]
    logger.debug("get_included_contacts() — returned %d included contacts: %s",
                 len(contacts), [c["name"] for c in contacts])
    return contacts


# ---- Company Verification Settings ----

async def get_company_verification(company_id: int) -> bool:
    logger.debug("get_company_verification(company_id=%d)", company_id)
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT require_verification FROM company_verification_settings WHERE company_id = $1",
        company_id,
    )
    result = row["require_verification"] if row else False
    logger.debug("get_company_verification(company_id=%d) — row_found=%s, require_verification=%s",
                 company_id, row is not None, result)
    return result


async def set_company_verification(company_id: int, require_verification: bool) -> None:
    logger.info("set_company_verification(company_id=%d, require=%s)", company_id, require_verification)
    pool = get_pool()
    await pool.execute("""
        INSERT INTO company_verification_settings (company_id, require_verification, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (company_id) DO UPDATE SET require_verification = $2, updated_at = NOW()
    """, company_id, require_verification)
    logger.info("set_company_verification(company_id=%d, require=%s) — upserted",
                company_id, require_verification)


async def get_all_company_verifications() -> list[dict]:
    logger.debug("get_all_company_verifications() — querying companies with verification settings")
    pool = get_pool()
    rows = await pool.fetch("""
        SELECT DISTINCT c.company_id, c.symbol, c.name,
               COALESCE(v.require_verification, FALSE) AS require_verification
        FROM company c
        INNER JOIN eloc_deal d ON c.company_id = d.company_id
            AND d.expiration_date >= CURRENT_DATE
        LEFT JOIN company_verification_settings v ON c.company_id = v.company_id
        ORDER BY c.name
    """)
    results = [dict(r) for r in rows]
    verified_count = sum(1 for r in results if r["require_verification"])
    logger.debug("get_all_company_verifications() — %d companies, %d with verification enabled",
                 len(results), verified_count)
    return results

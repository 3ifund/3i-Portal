"""
3i Fund Portal — Countersign Token Repository
Manages countersign_tokens table in PostgreSQL (DealTerms DB).
Used for SMS-based Purchase Confirmation countersigning.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.database.postgres import get_pool

logger = logging.getLogger("portal.countersign")

TOKEN_EXPIRY_HOURS = 24


# ---- Table Creation ----

async def ensure_countersign_tables() -> None:
    """Create the countersign_tokens table if it doesn't exist."""
    pool = get_pool()

    await pool.execute("""
        CREATE TABLE IF NOT EXISTS countersign_tokens (
            token           VARCHAR(255)    PRIMARY KEY,
            group_id        VARCHAR(255)    NOT NULL,
            signatory_id    INTEGER         NOT NULL,
            signatory_name  VARCHAR(255)    NOT NULL,
            signatory_phone VARCHAR(50)     NOT NULL,
            company_name    VARCHAR(255)    NOT NULL,
            eloc_id         VARCHAR(255)    NOT NULL,
            status          VARCHAR(20)     NOT NULL DEFAULT 'pending',
            created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            expires_at      TIMESTAMPTZ     NOT NULL,
            responded_at    TIMESTAMPTZ     NULL
        )
    """)
    logger.info("countersign_tokens table ensured")

    await pool.execute("""
        CREATE TABLE IF NOT EXISTS company_countersign_settings (
            company_id              INTEGER     PRIMARY KEY REFERENCES company(company_id),
            enable_countersign_sms  BOOLEAN     NOT NULL DEFAULT FALSE,
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    logger.info("company_countersign_settings table ensured")


# ---- Token CRUD ----

async def create_countersign_token(
    group_id: str,
    signatory_id: int,
    signatory_name: str,
    signatory_phone: str,
    company_name: str,
    eloc_id: str,
) -> dict:
    """Create a countersign token for a signatory. Returns dict with token and url."""
    token = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=TOKEN_EXPIRY_HOURS)

    logger.info("create_countersign_token — group=%s, signatory=%s (%s), eloc=%s",
                group_id, signatory_name, signatory_phone, eloc_id)

    pool = get_pool()
    await pool.execute(
        """INSERT INTO countersign_tokens
           (token, group_id, signatory_id, signatory_name, signatory_phone,
            company_name, eloc_id, status, created_at, expires_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', $8, $9)""",
        token, group_id, signatory_id, signatory_name, signatory_phone,
        company_name, eloc_id, now, expires_at,
    )

    url = f"/countersign/{token}"
    logger.info("create_countersign_token — token=%s, url=%s, expires=%s",
                token[:12] + "...", url, expires_at.isoformat())
    return {"token": token, "url": url}


async def get_countersign_token(token: str) -> dict | None:
    """Look up a countersign token. Returns dict or None."""
    logger.debug("get_countersign_token — token=%s", token[:12] + "...")
    pool = get_pool()
    row = await pool.fetchrow(
        """SELECT token, group_id, signatory_id, signatory_name, signatory_phone,
                  company_name, eloc_id, status, created_at, expires_at, responded_at
           FROM countersign_tokens WHERE token = $1""",
        token,
    )
    if not row:
        logger.debug("get_countersign_token — not found")
        return None
    return dict(row)


async def check_group_responded(group_id: str) -> dict | None:
    """Check if any token in the group has already been responded to.
    Returns the first approved/rejected token dict, or None."""
    logger.debug("check_group_responded — group=%s", group_id)
    pool = get_pool()
    row = await pool.fetchrow(
        """SELECT signatory_name, status
           FROM countersign_tokens
           WHERE group_id = $1 AND status IN ('approved', 'rejected')
           LIMIT 1""",
        group_id,
    )
    if row:
        logger.debug("check_group_responded — group=%s already responded by %s (%s)",
                      group_id, row["signatory_name"], row["status"])
        return dict(row)
    return None


async def try_claim_token(token: str, status: str) -> bool:
    """Atomically claim a token — UPDATE only if still pending.
    Returns True if this call claimed it, False if already claimed (race-safe)."""
    logger.info("try_claim_token — token=%s, status=%s", token[:12] + "...", status)
    now = datetime.now(timezone.utc)
    pool = get_pool()
    row = await pool.fetchrow(
        "UPDATE countersign_tokens SET status = $1, responded_at = $2 WHERE token = $3 AND status = 'pending' RETURNING token",
        status, now, token,
    )
    claimed = row is not None
    logger.info("try_claim_token — token=%s, claimed=%s", token[:12] + "...", claimed)
    return claimed


async def mark_token_responded(token: str, status: str) -> None:
    """Mark a token as approved or rejected."""
    logger.info("mark_token_responded — token=%s, status=%s", token[:12] + "...", status)
    now = datetime.now(timezone.utc)
    pool = get_pool()
    await pool.execute(
        "UPDATE countersign_tokens SET status = $1, responded_at = $2 WHERE token = $3",
        status, now, token,
    )


async def supersede_group_tokens(group_id: str, except_token: str) -> None:
    """Mark all other pending tokens in the group as superseded."""
    logger.info("supersede_group_tokens — group=%s, except=%s", group_id, except_token[:12] + "...")
    now = datetime.now(timezone.utc)
    pool = get_pool()
    result = await pool.execute(
        """UPDATE countersign_tokens
           SET status = 'superseded', responded_at = $1
           WHERE group_id = $2 AND token != $3 AND status = 'pending'""",
        now, group_id, except_token,
    )
    logger.info("supersede_group_tokens — group=%s, result=%s", group_id, result)


async def supersede_all_tokens_for_eloc(eloc_id: str) -> None:
    """Supersede ALL pending countersign tokens for an ELOC.
    Called when Portal UI countersign completes (prevents stale SMS links)."""
    logger.info("supersede_all_tokens_for_eloc — eloc_id=%s", eloc_id)
    now = datetime.now(timezone.utc)
    pool = get_pool()
    result = await pool.execute(
        """UPDATE countersign_tokens
           SET status = 'superseded', responded_at = $1
           WHERE eloc_id = $2 AND status = 'pending'""",
        now, eloc_id,
    )
    logger.info("supersede_all_tokens_for_eloc — eloc_id=%s, result=%s", eloc_id, result)


async def has_pending_countersign(eloc_id: str) -> bool:
    """Check if countersign SMS tokens have already been created for this ELOC.
    Prevents duplicate sends on WebSocket reconnect."""
    logger.debug("has_pending_countersign — eloc_id=%s", eloc_id)
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT 1 FROM countersign_tokens WHERE eloc_id = $1 LIMIT 1",
        eloc_id,
    )
    exists = row is not None
    logger.debug("has_pending_countersign — eloc_id=%s, exists=%s", eloc_id, exists)
    return exists


# ---- Company Countersign SMS Settings ----

async def get_countersign_sms_enabled(company_id: int) -> bool:
    """Check if countersign SMS is enabled for a company."""
    logger.debug("get_countersign_sms_enabled(company_id=%d)", company_id)
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT enable_countersign_sms FROM company_countersign_settings WHERE company_id = $1",
        company_id,
    )
    result = row["enable_countersign_sms"] if row else False
    logger.debug("get_countersign_sms_enabled(company_id=%d) — row_found=%s, enabled=%s",
                 company_id, row is not None, result)
    return result


async def set_countersign_sms_enabled(company_id: int, enabled: bool) -> None:
    """Set whether countersign SMS is enabled for a company (upsert)."""
    logger.info("set_countersign_sms_enabled(company_id=%d, enabled=%s)", company_id, enabled)
    pool = get_pool()
    await pool.execute("""
        INSERT INTO company_countersign_settings (company_id, enable_countersign_sms, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (company_id) DO UPDATE SET enable_countersign_sms = $2, updated_at = NOW()
    """, company_id, enabled)
    logger.info("set_countersign_sms_enabled(company_id=%d, enabled=%s) — upserted",
                company_id, enabled)


async def get_all_countersign_settings() -> list[dict]:
    """List all companies with active ELOC deals and their countersign SMS settings."""
    logger.debug("get_all_countersign_settings() — querying companies with countersign settings")
    pool = get_pool()
    rows = await pool.fetch("""
        SELECT DISTINCT c.company_id, c.symbol, c.name,
               COALESCE(cs.enable_countersign_sms, FALSE) AS enable_countersign_sms
        FROM company c
        INNER JOIN eloc_deal d ON c.company_id = d.company_id
            AND d.expiration_date >= CURRENT_DATE
        LEFT JOIN company_countersign_settings cs ON c.company_id = cs.company_id
        ORDER BY c.name
    """)
    results = [dict(r) for r in rows]
    enabled_count = sum(1 for r in results if r["enable_countersign_sms"])
    logger.debug("get_all_countersign_settings() — %d companies, %d with countersign SMS enabled",
                 len(results), enabled_count)
    return results

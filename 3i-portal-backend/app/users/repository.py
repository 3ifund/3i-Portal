"""
3i Fund Portal — Users Repository
Manages the portal_users table in PostgreSQL for authentication.
Auto-creates the table and seeds the admin user on startup.
"""

import logging

import bcrypt

from app.database.postgres import get_pool

logger = logging.getLogger("portal.users")

# Seed admin credentials
_SEED_ADMIN_ID = "admin@3ifund.com"
_SEED_ADMIN_PASSWORD = "3iFund!!"


async def ensure_table_exists() -> None:
    """Create the portal_users table if it doesn't exist and seed the admin user."""
    pool = get_pool()

    await pool.execute("""
        CREATE TABLE IF NOT EXISTS portal_users (
            user_id             VARCHAR(255)    PRIMARY KEY,
            password_hash       VARCHAR(255)    NULL,
            role                VARCHAR(20)     NOT NULL DEFAULT 'user'
                                                CHECK (role IN ('user', 'admin')),
            company_id          INTEGER         NULL REFERENCES company(company_id),
            must_change_password BOOLEAN        NOT NULL DEFAULT TRUE,
            is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        )
    """)
    logger.info("portal_users table ensured")

    # Seed admin if not exists
    existing = await pool.fetchrow(
        "SELECT user_id FROM portal_users WHERE user_id = $1",
        _SEED_ADMIN_ID,
    )
    if not existing:
        hashed = bcrypt.hashpw(
            _SEED_ADMIN_PASSWORD.encode(), bcrypt.gensalt()
        ).decode()
        await pool.execute(
            """
            INSERT INTO portal_users
                (user_id, password_hash, role, company_id, must_change_password, is_active)
            VALUES ($1, $2, 'admin', NULL, FALSE, TRUE)
            """,
            _SEED_ADMIN_ID,
            hashed,
        )
        logger.info("Seeded admin user: %s", _SEED_ADMIN_ID)


async def get_user_by_id(user_id: str) -> dict | None:
    """Fetch a user by user_id (case-insensitive), joined with company."""
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT u.user_id, u.password_hash, u.role, u.company_id,
               u.must_change_password, u.is_active, u.created_at, u.updated_at,
               c.name AS company_name, c.symbol AS company_symbol
        FROM portal_users u
        LEFT JOIN company c ON u.company_id = c.company_id
        WHERE LOWER(u.user_id) = LOWER($1)
        """,
        user_id,
    )
    return dict(row) if row else None


async def create_user(
    user_id: str,
    password_hash: str | None,
    role: str = "user",
    company_id: int | None = None,
) -> dict:
    """Insert a new user and return the created row."""
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO portal_users
            (user_id, password_hash, role, company_id, must_change_password, is_active)
        VALUES ($1, $2, $3, $4, TRUE, TRUE)
        RETURNING user_id, role, company_id, must_change_password, is_active,
                  created_at, updated_at
        """,
        user_id.strip().lower(),
        password_hash,
        role,
        company_id,
    )
    return dict(row)


async def update_user(
    user_id: str,
    role: str | None = None,
    company_id: int | None = None,
    is_active: bool | None = None,
    clear_company: bool = False,
) -> dict | None:
    """Update user fields. Returns updated row or None if not found."""
    pool = get_pool()

    # Build SET clauses dynamically
    sets = ["updated_at = NOW()"]
    params = []
    idx = 1

    if role is not None:
        sets.append(f"role = ${idx}")
        params.append(role)
        idx += 1

    if clear_company:
        sets.append("company_id = NULL")
    elif company_id is not None:
        sets.append(f"company_id = ${idx}")
        params.append(company_id)
        idx += 1

    if is_active is not None:
        sets.append(f"is_active = ${idx}")
        params.append(is_active)
        idx += 1

    params.append(user_id)
    query = f"""
        UPDATE portal_users
        SET {', '.join(sets)}
        WHERE LOWER(user_id) = LOWER(${idx})
        RETURNING user_id, role, company_id, must_change_password, is_active,
                  created_at, updated_at
    """
    row = await pool.fetchrow(query, *params)
    return dict(row) if row else None


async def update_password(user_id: str, password_hash: str) -> bool:
    """Update password and clear must_change_password flag."""
    pool = get_pool()
    result = await pool.execute(
        """
        UPDATE portal_users
        SET password_hash = $1, must_change_password = FALSE, updated_at = NOW()
        WHERE LOWER(user_id) = LOWER($2)
        """,
        password_hash,
        user_id,
    )
    return result == "UPDATE 1"


async def reset_password(user_id: str, password_hash: str) -> bool:
    """Admin resets password: update hash and set must_change_password=TRUE."""
    pool = get_pool()
    result = await pool.execute(
        """
        UPDATE portal_users
        SET password_hash = $1, must_change_password = TRUE, updated_at = NOW()
        WHERE LOWER(user_id) = LOWER($2)
        """,
        password_hash,
        user_id,
    )
    return result == "UPDATE 1"


async def deactivate_user(user_id: str) -> bool:
    """Set is_active=FALSE for a user."""
    pool = get_pool()
    result = await pool.execute(
        """
        UPDATE portal_users
        SET is_active = FALSE, updated_at = NOW()
        WHERE LOWER(user_id) = LOWER($1)
        """,
        user_id,
    )
    return result == "UPDATE 1"


async def list_users() -> list[dict]:
    """Return all users joined with company info."""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT u.user_id, u.role, u.company_id,
               u.must_change_password, u.is_active, u.created_at, u.updated_at,
               c.name AS company_name, c.symbol AS company_symbol
        FROM portal_users u
        LEFT JOIN company c ON u.company_id = c.company_id
        ORDER BY u.created_at
        """
    )
    return [dict(r) for r in rows]

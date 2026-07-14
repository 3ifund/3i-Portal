
import logging

import bcrypt

from app.database.postgres import get_pool

logger = logging.getLogger("portal.users")

_SEED_ADMIN_ID = "admin@3ifund.com"
_SEED_ADMIN_PASSWORD = "3iFund!!"


async def ensure_table_exists() -> None:
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
            signatory_name      VARCHAR(255)    NOT NULL DEFAULT '',
            signatory_title     VARCHAR(255)    NOT NULL DEFAULT '',
            signatory_address   TEXT            NOT NULL DEFAULT '',
            signatory_phone_number VARCHAR(50)  NOT NULL DEFAULT '',
            signatory_signature_image BYTEA     NULL,
            created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
        )
    """)

    for col, typ in [
        ("signatory_name", "VARCHAR(255) NOT NULL DEFAULT ''"),
        ("signatory_title", "VARCHAR(255) NOT NULL DEFAULT ''"),
        ("signatory_address", "TEXT NOT NULL DEFAULT ''"),
        ("signatory_phone_number", "VARCHAR(50) NOT NULL DEFAULT ''"),
        ("signatory_signature_image", "BYTEA NULL"),
    ]:
        await pool.execute(f"""
            DO $$ BEGIN
                ALTER TABLE portal_users ADD COLUMN {col} {typ};
            EXCEPTION WHEN duplicate_column THEN NULL;
            END $$;
        """)

    logger.info("portal_users table ensured (with signatory columns)")

    existing = await pool.fetchrow(
        "SELECT user_id, is_active, role FROM portal_users WHERE user_id = $1",
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
    else:
        if not existing["is_active"] or existing["role"] != "admin":
            await pool.execute(
                """
                UPDATE portal_users
                SET is_active = TRUE, role = 'admin', updated_at = NOW()
                WHERE user_id = $1
                """,
                _SEED_ADMIN_ID,
            )
            logger.info("Re-activated seed admin: %s", _SEED_ADMIN_ID)


async def get_user_by_id(user_id: str) -> dict | None:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT u.user_id, u.password_hash, u.role, u.company_id,
               u.must_change_password, u.is_active,
               u.signatory_name, u.signatory_title, u.signatory_address,
               u.signatory_phone_number, u.signatory_signature_image,
               u.created_at, u.updated_at,
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
    signatory_name: str = "",
) -> dict:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO portal_users
            (user_id, password_hash, role, company_id, signatory_name, must_change_password, is_active)
        VALUES ($1, $2, $3, $4, $5, TRUE, TRUE)
        RETURNING user_id, role, company_id, signatory_name, must_change_password, is_active,
                  created_at, updated_at
        """,
        user_id.strip().lower(),
        password_hash,
        role,
        company_id,
        signatory_name,
    )
    return dict(row)


async def update_user(
    user_id: str,
    role: str | None = None,
    company_id: int | None = None,
    is_active: bool | None = None,
    clear_company: bool = False,
    signatory_name: str | None = None,
) -> dict | None:
    pool = get_pool()

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

    if signatory_name is not None:
        sets.append(f"signatory_name = ${idx}")
        params.append(signatory_name)
        idx += 1

    params.append(user_id)
    query = f"""
        UPDATE portal_users
        SET {', '.join(sets)}
        WHERE LOWER(user_id) = LOWER(${idx})
        RETURNING user_id, role, company_id, signatory_name, must_change_password, is_active,
                  created_at, updated_at
    """
    row = await pool.fetchrow(query, *params)
    return dict(row) if row else None


async def update_password(user_id: str, password_hash: str) -> bool:
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


async def hard_delete_user(user_id: str) -> bool:
    pool = get_pool()
    result = await pool.execute(
        "DELETE FROM portal_users WHERE LOWER(user_id) = LOWER($1)",
        user_id,
    )
    return result == "DELETE 1"


async def list_users() -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT u.user_id, u.role, u.company_id,
               u.must_change_password, u.is_active,
               u.signatory_name, u.signatory_title, u.signatory_address,
               u.signatory_phone_number,
               u.created_at, u.updated_at,
               c.name AS company_name, c.symbol AS company_symbol
        FROM portal_users u
        LEFT JOIN company c ON u.company_id = c.company_id
        ORDER BY u.created_at
        """
    )
    return [dict(r) for r in rows]


async def update_signatory_details(user_id: str, updates: dict) -> bool:
    import base64
    pool = get_pool()
    allowed = {"signatory_title", "signatory_address", "signatory_phone_number", "signatory_signature_image"}
    filtered = {k: v for k, v in updates.items() if k in allowed and v is not None}
    if not filtered:
        return False

    sets = ["updated_at = NOW()"]
    params = []
    idx = 1
    for key, val in filtered.items():
        if key == "signatory_signature_image" and isinstance(val, str):
            raw = val
            if "," in raw:
                raw = raw.split(",", 1)[1]
            val = base64.b64decode(raw)
        sets.append(f"{key} = ${idx}")
        params.append(val)
        idx += 1

    params.append(user_id)
    query = f"""
        UPDATE portal_users SET {', '.join(sets)}
        WHERE LOWER(user_id) = LOWER(${idx})
    """
    result = await pool.execute(query, *params)
    return result == "UPDATE 1"


async def get_user_signatory(user_id: str) -> dict | None:
    import base64
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT user_id, signatory_name, signatory_title, signatory_address,
               signatory_phone_number, signatory_signature_image
        FROM portal_users
        WHERE LOWER(user_id) = LOWER($1)
        """,
        user_id,
    )
    if not row:
        return None
    d = dict(row)
    sig = d.get("signatory_signature_image")
    if sig and isinstance(sig, (bytes, memoryview)):
        d["signatory_signature_image"] = f"data:image/png;base64,{base64.b64encode(bytes(sig)).decode()}"
    return d


async def get_company_users_with_phone(company_id: int) -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT user_id, signatory_name, signatory_phone_number
        FROM portal_users
        WHERE company_id = $1
          AND is_active = TRUE
          AND signatory_phone_number != ''
        """,
        company_id,
    )
    return [dict(r) for r in rows]


import logging

from app.database.postgres import get_pool

logger = logging.getLogger("portal.dealterms")


async def get_company_by_symbol(symbol: str) -> dict | None:
    logger.debug("get_company_by_symbol(%s)", symbol)
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT company_id, symbol, name, name_normalized, currency
        FROM company
        WHERE symbol = $1
        """,
        symbol,
    )
    if row:
        logger.debug("  → found: %s (id=%s)", row["name"], row["company_id"])
    else:
        logger.warning("  → symbol=%s not found", symbol)
    return dict(row) if row else None

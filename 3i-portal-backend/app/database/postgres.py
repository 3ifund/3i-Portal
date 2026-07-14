
import logging

import asyncpg

from app.config import settings

logger = logging.getLogger("portal.db.postgres")
_pool: asyncpg.Pool | None = None


async def connect_postgres():
    global _pool
    logger.info("Connecting to PostgreSQL at %s:%s/%s (user=%s)",
                settings.pg_host, settings.pg_port, settings.pg_database, settings.pg_user)
    _pool = await asyncpg.create_pool(
        host=settings.pg_host,
        port=settings.pg_port,
        database=settings.pg_database,
        user=settings.pg_user,
        password=settings.pg_password,
        min_size=2,
        max_size=10,
    )
    logger.info("PostgreSQL pool created (min=2, max=10)")


async def close_postgres():
    global _pool
    if _pool:
        await _pool.close()
        logger.info("PostgreSQL pool closed")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("PostgreSQL not connected. Call connect_postgres() first.")
    return _pool

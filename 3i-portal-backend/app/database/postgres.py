"""
3i Fund Portal — PostgreSQL Connection (DealTerms DB)
Uses asyncpg for async access to the on-prem DealTerms database.
"""

import logging

import asyncpg

from app.config import settings

logger = logging.getLogger("portal.db.postgres")
_pool: asyncpg.Pool | None = None


async def connect_postgres():
    """Create the asyncpg connection pool on app startup."""
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
    """Close the pool on app shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        logger.info("PostgreSQL pool closed")


def get_pool() -> asyncpg.Pool:
    """Return the connection pool. Call after connect_postgres()."""
    if _pool is None:
        raise RuntimeError("PostgreSQL not connected. Call connect_postgres() first.")
    return _pool

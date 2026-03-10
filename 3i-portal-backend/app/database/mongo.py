"""
3i Fund Portal — MongoDB Connection (portal_3i)
Uses Motor for async access to the portal_3i MongoDB database.
Stores purchase notice templates and user signatories.
"""

import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import settings

logger = logging.getLogger("portal.db.mongo")
_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect_mongo():
    """Create the Motor client and connect to portal_3i on app startup."""
    global _client, _db
    logger.info("Connecting to MongoDB at %s, db=%s", settings.mongo_uri, settings.mongo_db_name)
    _client = AsyncIOMotorClient(settings.mongo_uri)
    _db = _client[settings.mongo_db_name]
    await _client.admin.command("ping")
    logger.info("MongoDB connected")


async def close_mongo():
    """Close the Motor client on app shutdown."""
    global _client, _db
    if _client:
        _client.close()
        logger.info("MongoDB disconnected")
    _client = None
    _db = None


def get_db() -> AsyncIOMotorDatabase:
    """Return the database handle. Call after connect_mongo()."""
    if _db is None:
        raise RuntimeError("MongoDB not connected. Call connect_mongo() first.")
    return _db

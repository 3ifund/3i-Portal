"""
One-time migration: company_signatories from MongoDB to PostgreSQL.

Reads all documents from MongoDB three_i_fund_portal.company_signatories,
creates the PostgreSQL table if needed, and inserts rows.

Usage:
    cd 3i-portal-backend
    python migrate_signatories.py
"""

import asyncio
import base64
import sys

import asyncpg
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

from app.config import settings


async def migrate():
    # Connect to MongoDB
    print(f"Connecting to MongoDB: {settings.mongo_uri} / {settings.mongo_db_name}")
    mongo_client = AsyncIOMotorClient(settings.mongo_uri)
    db = mongo_client[settings.mongo_db_name]

    # Connect to PostgreSQL
    dsn = f"postgresql://{settings.pg_user}:{settings.pg_password}@{settings.pg_host}:{settings.pg_port}/{settings.pg_database}"
    print(f"Connecting to PostgreSQL: {settings.pg_host}:{settings.pg_port}/{settings.pg_database}")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)

    # Create table if not exists
    async with pool.acquire() as conn:
        await conn.execute("""
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
        print("PostgreSQL table ensured")

        # Check if table already has data
        count = await conn.fetchval("SELECT COUNT(*) FROM company_signatories")
        if count > 0:
            print(f"PostgreSQL table already has {count} rows. Skipping migration.")
            print("If you want to re-migrate, truncate the table first:")
            print("  TRUNCATE company_signatories RESTART IDENTITY;")
            await pool.close()
            mongo_client.close()
            return

    # Read all documents from MongoDB
    cursor = db.company_signatories.find({})
    docs = await cursor.to_list(length=1000)
    print(f"Found {len(docs)} company documents in MongoDB")

    if not docs:
        print("No documents to migrate.")
        await pool.close()
        mongo_client.close()
        return

    total_inserted = 0

    async with pool.acquire() as conn:
        for doc in docs:
            company_id = doc.get("company_id")
            signatories = doc.get("signatories", [])

            if not company_id:
                print(f"  Skipping document with no company_id: {doc.get('_id')}")
                continue

            print(f"  Company {company_id}: {len(signatories)} signatories")

            for sig in signatories:
                name = sig.get("name", "")
                title = sig.get("title", "")
                address = sig.get("address", "")
                signature_image_b64 = sig.get("signature_image")

                # Convert base64 data URI to raw bytes
                signature_bytes = None
                if signature_image_b64:
                    try:
                        # Strip data URI prefix if present
                        if "," in signature_image_b64:
                            signature_image_b64 = signature_image_b64.split(",", 1)[1]
                        signature_bytes = base64.b64decode(signature_image_b64)
                    except Exception as e:
                        print(f"    Warning: Failed to decode signature for {name}: {e}")

                try:
                    await conn.execute(
                        """INSERT INTO company_signatories
                           (company_id, name, title, address, signature_image)
                           VALUES ($1, $2, $3, $4, $5)""",
                        company_id, name, title, address, signature_bytes,
                    )
                    total_inserted += 1
                    has_sig = "yes" if signature_bytes else "no"
                    print(f"    Inserted: {name} (title={title}, signature={has_sig})")
                except Exception as e:
                    print(f"    ERROR inserting {name} for company {company_id}: {e}")

    print(f"\nMigration complete: {total_inserted} signatories inserted into PostgreSQL")
    print("\nYou can now drop the MongoDB collection if everything looks correct:")
    print(f"  db.company_signatories.drop()")

    await pool.close()
    mongo_client.close()


if __name__ == "__main__":
    asyncio.run(migrate())

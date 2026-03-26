"""
3i Fund Portal — FastAPI Application Entry Point
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging_config import setup_logging
from app.database.postgres import connect_postgres, close_postgres
from app.database.mongo import connect_mongo, close_mongo
from app.auth.router import router as auth_router
from app.elocs.router import router as elocs_router
from app.admin.router import router as admin_router
from app.quotes.router import router as quotes_router
from app.workflows.router import router as workflows_router, connect_dealterms_ws
from app.admin.users_router import router as admin_users_router
from app.purchase_notices.admin_router import router as pn_admin_router
from app.purchase_notices.router import router as pn_router
from app.approval.router import router as approval_router
from app.approval.admin_router import router as approval_admin_router
from app.users.repository import ensure_table_exists
from app.approval.repository import ensure_approval_tables
from app.purchase_notices.pg_repository import ensure_company_signatories_table
from app.countersign.repository import ensure_countersign_tables
from app.countersign.router import router as countersign_router

# Initialize logging before anything else
setup_logging()
logger = logging.getLogger("portal.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("=== 3i Fund Portal starting up ===")
    logger.info("CORS origins: %s", settings.cors_origins)
    logger.info("On-prem base URL: %s", settings.onprem_base_url)
    logger.info("PostgreSQL: %s@%s:%s/%s", settings.pg_user, settings.pg_host, settings.pg_port, settings.pg_database)

    if settings.jwt_secret == "CHANGE-ME-IN-PRODUCTION":
        logger.warning("=" * 60)
        logger.warning("  WARNING: Using default JWT secret!")
        logger.warning("  Set JWT_SECRET environment variable for production.")
        logger.warning("=" * 60)

    await connect_postgres()
    logger.info("PostgreSQL connected")

    await ensure_table_exists()
    logger.info("Users table ensured")

    await ensure_approval_tables()
    logger.info("Approval tables ensured")

    await ensure_company_signatories_table()
    logger.info("Company signatories table ensured")

    await ensure_countersign_tables()
    logger.info("Countersign tokens table ensured")

    await connect_mongo()
    logger.info("MongoDB connected")

    # Connect to DealTermsServer WebSocket for workflow state updates
    watcher_task = asyncio.create_task(connect_dealterms_ws())
    logger.info("DealTermsServer WebSocket client started")

    yield

    logger.info("=== 3i Fund Portal shutting down ===")
    watcher_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass
    logger.info("DealTermsServer WebSocket client stopped")
    await close_mongo()
    logger.info("MongoDB disconnected")
    await close_postgres()
    logger.info("PostgreSQL disconnected")


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(elocs_router, prefix="/elocs", tags=["elocs"])
app.include_router(admin_router, prefix="/admin", tags=["admin"])
app.include_router(admin_users_router, prefix="/admin", tags=["admin-users"])
app.include_router(pn_admin_router, prefix="/admin", tags=["admin-templates"])
app.include_router(pn_router, prefix="/purchase-notices", tags=["purchase-notices"])
app.include_router(quotes_router, prefix="/ws", tags=["quotes"])
app.include_router(workflows_router, prefix="/ws", tags=["workflows"])
app.include_router(approval_router, tags=["approval"])
app.include_router(approval_admin_router, prefix="/admin", tags=["admin-approval"])
app.include_router(countersign_router, tags=["countersign"])


@app.get("/health")
async def health():
    return {"status": "ok"}

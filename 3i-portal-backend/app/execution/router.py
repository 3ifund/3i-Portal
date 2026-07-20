import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.onprem import client as onprem

logger = logging.getLogger("portal.execution")
router = APIRouter()


class GatewayConfig(BaseModel):
    serverAddress: str
    serverPort: int
    connectionTimeoutSeconds: int = 10
    pingIntervalSeconds: int = 25
    traderId: str | None = None
    autoConnect: bool = True


@router.get("/status")
async def get_status(admin: UserInfo = Depends(require_admin)):
    try:
        return await onprem.get_execution_status()
    except Exception as exc:
        logger.error("status — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.get("/config")
async def get_config(admin: UserInfo = Depends(require_admin)):
    try:
        return await onprem.get_execution_config()
    except Exception as exc:
        logger.error("config get — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.put("/config")
async def put_config(body: GatewayConfig, reconnect: bool = True, admin: UserInfo = Depends(require_admin)):
    logger.info("PUT /internal/execution/config -> %s:%s reconnect=%s by user=%s", body.serverAddress, body.serverPort, reconnect, admin.user_id)
    try:
        return await onprem.update_execution_config(body.model_dump(), reconnect)
    except Exception as exc:
        logger.error("config put — DTS FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.post("/connect")
async def connect(admin: UserInfo = Depends(require_admin)):
    logger.info("POST /internal/execution/connect by user=%s", admin.user_id)
    try:
        return await onprem.execution_connect()
    except Exception as exc:
        logger.error("connect — DTS FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.post("/disconnect")
async def disconnect(admin: UserInfo = Depends(require_admin)):
    logger.info("POST /internal/execution/disconnect by user=%s", admin.user_id)
    try:
        return await onprem.execution_disconnect()
    except Exception as exc:
        logger.error("disconnect — DTS FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.onprem import client as onprem

logger = logging.getLogger("portal.action_items")
router = APIRouter()


@router.get("")
async def list_action_items(admin: UserInfo = Depends(require_admin)):
    logger.info("GET /internal/action-items by user=%s", admin.user_id)
    try:
        return await onprem.get_action_items()
    except Exception as exc:
        logger.error("action-items list — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.get("/count")
async def action_items_count(admin: UserInfo = Depends(require_admin)):
    try:
        return await onprem.get_action_items_count()
    except Exception as exc:
        logger.error("action-items count — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.delete("/{item_id}")
async def remove_action_item(item_id: int, admin: UserInfo = Depends(require_admin)):
    logger.info("DELETE /internal/action-items/%s by user=%s", item_id, admin.user_id)
    try:
        status, body = await onprem.remove_action_item(item_id)
    except Exception as exc:
        logger.error("action-items remove — DTS FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")
    if status >= 400:
        raise HTTPException(status_code=status, detail=body)
    return body


@router.post("/{item_id}/retry")
async def retry_action_item(item_id: int, admin: UserInfo = Depends(require_admin)):
    logger.info("POST /internal/action-items/%s/retry by user=%s", item_id, admin.user_id)
    try:
        status, body = await onprem.retry_action_item(item_id)
    except Exception as exc:
        logger.error("action-items retry — DTS FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")
    if status >= 400:
        raise HTTPException(status_code=status, detail=body)
    return body

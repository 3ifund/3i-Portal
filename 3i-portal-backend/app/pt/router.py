import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.onprem import client as onprem

logger = logging.getLogger("portal.pt")
router = APIRouter()


class OverTheWallBody(BaseModel):
    overTheWall: bool
    userName: str | None = None


@router.get("/companies")
async def get_companies(admin: UserInfo = Depends(require_admin)):
    try:
        return await onprem.get_pt_companies()
    except Exception as exc:
        logger.error("companies — DTS fetch FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")


@router.put("/companies/{company_id}/over-the-wall")
async def set_over_the_wall(company_id: int, body: OverTheWallBody, admin: UserInfo = Depends(require_admin)):
    payload = body.model_dump()
    if not payload.get("userName"):
        payload["userName"] = admin.user_id
    logger.info("PUT /internal/pt/companies/%s/over-the-wall -> %s by user=%s", company_id, payload["overTheWall"], admin.user_id)
    try:
        return await onprem.set_pt_company_over_the_wall(company_id, payload)
    except Exception as exc:
        logger.error("over-the-wall — DTS FAILED: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"DTS upstream error: {exc}")

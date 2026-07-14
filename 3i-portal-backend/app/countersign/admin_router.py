
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.countersign import repository as repo

logger = logging.getLogger("portal.admin.countersign")
router = APIRouter()



class CountersignSmsRequest(BaseModel):
    enable_countersign_sms: bool



@router.get("/countersign-settings")
async def list_countersign_settings(admin: UserInfo = Depends(require_admin)):
    logger.info("GET /countersign-settings — admin=%s", admin.user_id)
    return await repo.get_all_countersign_settings()


@router.put("/countersign-settings/{company_id}")
async def set_countersign_sms(
    company_id: int,
    request: CountersignSmsRequest,
    admin: UserInfo = Depends(require_admin),
):
    logger.info("PUT /countersign-settings/%d — enabled=%s admin=%s",
                company_id, request.enable_countersign_sms, admin.user_id)
    await repo.set_countersign_sms_enabled(company_id, request.enable_countersign_sms)
    return {"status": "updated"}

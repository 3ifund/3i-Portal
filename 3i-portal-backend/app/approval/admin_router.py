
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.dependencies import require_admin
from app.auth.models import UserInfo
from app.approval import repository as repo

logger = logging.getLogger("portal.admin.approval")
router = APIRouter()



class ContactRequest(BaseModel):
    name: str
    phone_number: str


class ContactIncludeRequest(BaseModel):
    include: bool


class CompanyVerificationRequest(BaseModel):
    require_verification: bool



@router.get("/approval-contacts")
async def list_contacts(admin: UserInfo = Depends(require_admin)):
    logger.info("GET /approval-contacts — admin=%s", admin.user_id)
    return await repo.get_approval_contacts()


@router.post("/approval-contacts", status_code=201)
async def add_contact(request: ContactRequest, admin: UserInfo = Depends(require_admin)):
    logger.info("POST /approval-contacts — name=%s phone=%s admin=%s",
                request.name, request.phone_number, admin.user_id)
    return await repo.create_approval_contact(request.name, request.phone_number)


@router.put("/approval-contacts/{contact_id}")
async def update_contact(contact_id: int, request: ContactRequest, admin: UserInfo = Depends(require_admin)):
    logger.info("PUT /approval-contacts/%d — name=%s phone=%s admin=%s",
                contact_id, request.name, request.phone_number, admin.user_id)
    ok = await repo.update_approval_contact(contact_id, request.name, request.phone_number)
    if not ok:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"status": "updated"}


@router.delete("/approval-contacts/{contact_id}")
async def delete_contact(contact_id: int, admin: UserInfo = Depends(require_admin)):
    logger.info("DELETE /approval-contacts/%d — admin=%s", contact_id, admin.user_id)
    ok = await repo.delete_approval_contact(contact_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"status": "deleted"}


@router.put("/approval-contacts/{contact_id}/include")
async def toggle_contact_include(contact_id: int, request: ContactIncludeRequest, admin: UserInfo = Depends(require_admin)):
    logger.info("PUT /approval-contacts/%d/include — include=%s admin=%s",
                contact_id, request.include, admin.user_id)
    ok = await repo.set_contact_include(contact_id, request.include)
    if not ok:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"status": "updated"}



@router.get("/company-verifications")
async def list_company_verifications(admin: UserInfo = Depends(require_admin)):
    logger.info("GET /company-verifications — admin=%s", admin.user_id)
    return await repo.get_all_company_verifications()


@router.put("/company-verifications/{company_id}")
async def set_company_verification(
    company_id: int,
    request: CompanyVerificationRequest,
    admin: UserInfo = Depends(require_admin),
):
    logger.info("PUT /company-verifications/%d — require=%s admin=%s",
                company_id, request.require_verification, admin.user_id)
    await repo.set_company_verification(company_id, request.require_verification)
    return {"status": "updated"}

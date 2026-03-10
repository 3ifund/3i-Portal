"""
3i Fund Portal — Admin Response Schemas
"""

from pydantic import BaseModel


class CompanySummary(BaseModel):
    company_id: str
    name: str
    active_elocs: int = 0
    total_elocs: int = 0
    last_activity: str | None = None


class AdminElocSummary(BaseModel):
    eloc_id: str
    company_id: str
    company_name: str
    type: str | None = None
    status: str
    current_workflow_step: str | None = None
    created_at: str | None = None


class AdminPurchaseNotice(BaseModel):
    notice_id: str | None = None
    company_id: str
    company_name: str
    eloc_id: str
    shares: int
    estimated_value: float | None = None
    status: str
    submitted_at: str | None = None

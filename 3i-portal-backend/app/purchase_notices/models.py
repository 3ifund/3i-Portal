"""
3i Fund Portal — Purchase Notice Models
Pydantic models for templates, signatories, and prefill responses.
"""

from pydantic import BaseModel


# ---- Templates (admin-managed, stored in MongoDB) ----

class UpsertTemplateRequest(BaseModel):
    body_text: str
    agreed_accepted_entity: str


# ---- Signatories (user-managed) ----

class CreateSignatoryRequest(BaseModel):
    name: str
    title: str
    address: str
    email: str
    signature_image: str | None = None


class UpdateSignatoryRequest(BaseModel):
    name: str | None = None
    title: str | None = None
    address: str | None = None
    email: str | None = None
    signature_image: str | None = None


# ---- Company Signatories (admin-managed names, client-entered details, stored in PostgreSQL) ----

class AdminAddSignatoryRequest(BaseModel):
    name: str


class AdminUpdateSignatoryNameRequest(BaseModel):
    name: str


class UpdateSignatoryDetailsRequest(BaseModel):
    title: str | None = None
    address: str | None = None
    phone_number: str | None = None
    signature_image: str | None = None


# ---- Portal-Initiated Purchase Notice Submission ----

class PortalPurchaseNoticeRequest(BaseModel):
    """Full payload for submitting a portal-initiated purchase notice to DTS."""
    symbol: str
    pricing_period_id: int
    shares: int
    # Template content
    body_text: str = ""
    agreed_accepted_entity: str = ""
    # Company signatory (selected in dropdown)
    signatory_name: str
    signatory_title: str
    signatory_address: str = ""
    signatory_signature_image: str | None = None  # base64 data URI
    # Calculated fields from prefill
    exercise_date: str
    valuation_period_start: str
    valuation_period_end: str
    trading_days: int
    settlement_date: str
    period_type: str
    total_commitment_remaining: float | None = None
    dollar_cap_per_notice: float | None = None

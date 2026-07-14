
from pydantic import BaseModel



class UpsertTemplateRequest(BaseModel):
    body_text: str
    agreed_accepted_entity: str



class UpdateSignatoryDetailsRequest(BaseModel):
    title: str | None = None
    address: str | None = None
    phone_number: str | None = None
    signature_image: str | None = None



class PortalPurchaseNoticeRequest(BaseModel):
    """Full payload for submitting a portal-initiated purchase notice to DTS."""
    symbol: str
    pricing_period_id: int
    shares: int
    body_text: str = ""
    agreed_accepted_entity: str = ""
    signatory_name: str = ""
    signatory_title: str = ""
    signatory_address: str = ""
    signatory_signature_image: str | None = None
    exercise_date: str
    valuation_period_start: str
    valuation_period_end: str
    trading_days: int
    settlement_date: str
    period_type: str
    total_commitment_remaining: float | None = None
    dollar_cap_per_notice: float | None = None
    pricing_direction: str = "Forward"
    backward_vwap_price: float | None = None

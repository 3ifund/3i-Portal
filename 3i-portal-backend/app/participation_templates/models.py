"""
3i Fund Portal — Participation-ELOC Template Models

Pydantic models for the new participation-based ELOC Purchase Notice / Purchase
Confirmation templates. These are NAMED, company-specific templates whose fields are
chosen from the DealTermsServer field catalog
(GET /api/template-field-catalog/{documentType}).

Separate from the legacy `purchase_notices` templates — nothing here touches the
existing collections.
"""

from pydantic import BaseModel, Field

# Document types must match DealTermsServer's TemplateDocumentType enum.
DOCUMENT_TYPES: tuple[str, ...] = ("PurchaseNotice", "PurchaseConfirmation")


class TemplateField(BaseModel):
    """One catalog field placed on a template, with the admin's label text."""

    key: str                                # catalog enum key, e.g. "PurchaseShareAmount"
    label: str                              # admin-entered display label
    visible: bool = True
    order: int = 0
    options_config: dict | None = None      # extra config for OptionSet / CheckOrFill / etc.


class UpsertParticipationTemplateRequest(BaseModel):
    """Create/update payload for a named participation template."""

    name: str
    company_id: int
    document_type: str                      # one of DOCUMENT_TYPES
    body_text: str = ""
    agreed_accepted_entity: str = ""
    fields: list[TemplateField] = Field(default_factory=list)


class UpsertMappingRequest(BaseModel):
    """Maps a (company, pricing period, document type) to a named template."""

    company_id: int
    pricing_period_type: str
    document_type: str                      # one of DOCUMENT_TYPES
    template_id: str

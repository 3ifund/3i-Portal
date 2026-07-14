
from typing import Literal

from pydantic import BaseModel, Field

DOCUMENT_TYPES: tuple[str, ...] = ("PurchaseNotice", "PurchaseConfirmation")
DocumentType = Literal["PurchaseNotice", "PurchaseConfirmation"]

AllocationType = Literal["Known", "Unknown"]


class TemplateField(BaseModel):
    """One catalog field placed on a template, with the admin's label text."""

    key: str
    label: str
    note: str | None = None
    visible: bool = True
    order: int = 0
    options_config: dict | None = None


class UpsertParticipationTemplateRequest(BaseModel):
    """Create/update payload for a named participation template."""

    name: str
    company_id: int
    document_type: DocumentType
    allocation_type: AllocationType = "Known"
    body_text: str = ""
    agreed_accepted_entity: str = ""
    fields: list[TemplateField] = Field(default_factory=list)


class UpsertMappingRequest(BaseModel):
    """Maps a (company, pricing period, document type) to a named template."""

    company_id: int
    pricing_period_type: str
    document_type: DocumentType
    template_id: str

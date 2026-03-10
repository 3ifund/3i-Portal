"""
3i Fund Portal — Purchase Notice Models
Pydantic models for templates, signatories, and prefill responses.
"""

from pydantic import BaseModel


# ---- Templates (admin-managed, stored in MongoDB) ----

class UpsertTemplateRequest(BaseModel):
    body_text: str
    agreed_accepted_entity: str


# ---- Signatories (user-managed, stored in MongoDB) ----

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

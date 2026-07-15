
from pydantic import BaseModel


class MapTemplateRequest(BaseModel):
    """Maps a convertible-note tranche/class (by DTS instrument_id) to a conversion-notice template."""

    instrument_id: int
    template_id: str

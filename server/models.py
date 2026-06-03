from typing import Literal
from pydantic import BaseModel


class FlagRequest(BaseModel):
    edcs_id: str
    category: Literal["people", "translation", "summary", "other"]
    comment: str | None = None
    email: str | None = None

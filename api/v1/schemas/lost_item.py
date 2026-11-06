from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl

from api.v1.models.item import ItemStatus


class LostItemCreate(BaseModel):
    item_name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    color: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=2000)
    # Optional: owners often have no photo of what they lost.
    photo: Optional[HttpUrl] = None
    # Private: only the owner and staff see it, so it can back up a claim.
    identifying_marks: Optional[str] = Field(default=None, max_length=500)
    last_seen_location: str = Field(min_length=1, max_length=255)
    date_lost: date


class LostItemOut(LostItemCreate):
    id: str
    user_id: str
    status: ItemStatus
    created_at: datetime

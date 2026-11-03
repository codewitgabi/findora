from datetime import date, datetime

from pydantic import BaseModel, Field, HttpUrl

from api.v1.models.item import ItemStatus


class LostItemCreate(BaseModel):
    item_name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    color: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=2000)
    photo: HttpUrl
    last_seen_location: str = Field(min_length=1, max_length=255)
    date_lost: date


class LostItemOut(LostItemCreate):
    id: str
    user_id: str
    status: ItemStatus
    created_at: datetime

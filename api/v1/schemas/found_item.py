from datetime import date, datetime

from pydantic import BaseModel, Field, HttpUrl

from api.v1.models.item import HandedTo, ItemCondition, ItemStatus


class FoundItemCreate(BaseModel):
    item_name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    color: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=2000)
    photo: HttpUrl
    found_location: str = Field(min_length=1, max_length=255)
    date_found: date
    condition: ItemCondition
    handed_to: HandedTo


class FoundItemOut(FoundItemCreate):
    id: str
    user_id: str
    status: ItemStatus
    created_at: datetime

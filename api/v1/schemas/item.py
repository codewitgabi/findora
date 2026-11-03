from datetime import datetime
from typing import Optional

from pydantic import BaseModel, HttpUrl

from api.v1.models.claim import ClaimStatus
from api.v1.models.item import ItemCondition, ItemStatus, ReportType


class ItemSearchResult(BaseModel):
    id: str
    item_name: str
    report_type: ReportType
    location: str
    date: str
    photo: HttpUrl
    score: Optional[float] = None


class SimilarItem(BaseModel):
    id: str
    item_name: str
    location: str
    score: float


class MyClaimRef(BaseModel):
    id: str
    status: ClaimStatus


class ItemDetailOut(BaseModel):
    """Public item detail. Never carries any reporter contact data."""

    id: str
    report_type: ReportType
    item_name: str
    category: str
    color: str
    description: str
    photo: HttpUrl
    location: str
    date: str
    status: ItemStatus
    condition: Optional[ItemCondition] = None
    created_at: datetime
    is_owner: bool
    similar_items: list[SimilarItem]
    my_claim: Optional[MyClaimRef] = None


class MyReportOut(BaseModel):
    id: str
    report_type: ReportType
    item_name: str
    last_seen_or_found_location: str
    status: ItemStatus
    created_at: datetime


class MySummaryOut(BaseModel):
    my_reports: int
    active_matches: int
    claims_pending: int

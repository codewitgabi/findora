from datetime import date as Date
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl

from api.v1.models.claim import ClaimStatus, HandoverStatus
from api.v1.models.item import CloseReason, HandedTo, ItemCondition, ItemStatus, ReportType


class ItemSearchResult(BaseModel):
    id: str
    item_name: str
    report_type: ReportType
    location: str
    date: str
    photo: Optional[HttpUrl] = None
    score: Optional[float] = None


class SimilarItem(BaseModel):
    id: str
    item_name: str
    location: str
    score: float


class MyClaimRef(BaseModel):
    id: str
    status: ClaimStatus
    pickup_location: Optional[str] = None
    handover_status: Optional[HandoverStatus] = None


class MatchedItemRef(BaseModel):
    """A report that matching linked to this one. Shown to the owner and admins."""

    id: str
    item_name: str
    report_type: ReportType
    location: str
    status: ItemStatus


class HandoverRef(BaseModel):
    """The approved claim on the viewer's own report, so they can arrange the handover."""

    claim_id: str
    pickup_location: Optional[str] = None
    handover_status: Optional[HandoverStatus] = None


class ItemDetailOut(BaseModel):
    """Public item detail. Never carries any reporter contact data."""

    id: str
    report_type: ReportType
    item_name: str
    category: str
    color: str
    description: str
    photo: Optional[HttpUrl] = None
    location: str
    date: str
    status: ItemStatus
    condition: Optional[ItemCondition] = None
    handed_to: Optional[HandedTo] = None
    # Only returned to the owner and staff.
    identifying_marks: Optional[str] = None
    close_reason: Optional[CloseReason] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_owner: bool
    similar_items: list[SimilarItem]
    matched_items: list[MatchedItemRef] = []
    handover: Optional[HandoverRef] = None
    my_claim: Optional[MyClaimRef] = None


class ItemUpdateIn(BaseModel):
    """Owner edits. Send only the fields that change; which ones apply depends on the
    report type (``identifying_marks`` is lost-only, ``condition``/``handed_to``
    found-only)."""

    item_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    category: Optional[str] = Field(default=None, min_length=1, max_length=80)
    color: Optional[str] = Field(default=None, min_length=1, max_length=50)
    description: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    photo: Optional[HttpUrl] = None
    location: Optional[str] = Field(default=None, min_length=1, max_length=255)
    date: Optional[Date] = None
    identifying_marks: Optional[str] = Field(default=None, max_length=500)
    condition: Optional[ItemCondition] = None
    handed_to: Optional[HandedTo] = None


class ItemCloseIn(BaseModel):
    reason: CloseReason
    note: Optional[str] = Field(default=None, max_length=500)


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

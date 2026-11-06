from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, HttpUrl

from api.v1.models.claim import ClaimRole, ClaimStatus, HandoverStatus
from api.v1.models.item import HandedTo, ItemStatus, ReportType


class ClaimCreate(BaseModel):
    evidence_text: str = Field(min_length=10, max_length=2000)


class ClaimCreatedOut(BaseModel):
    id: str
    item_id: str
    status: ClaimStatus
    created_at: datetime


class MyClaimOut(BaseModel):
    id: str
    item_id: str
    item_name: str
    item_location: str
    evidence_text: str
    status: ClaimStatus
    admin_note: Optional[str] = None
    pickup_location: Optional[str] = None
    handover_status: Optional[HandoverStatus] = None
    collected_at: Optional[datetime] = None
    created_at: datetime


class AdminClaimOut(BaseModel):
    id: str
    item_id: str
    item_name: str
    item_location: str
    item_report_type: Optional[ReportType] = None
    item_handed_to: Optional[HandedTo] = None
    reporter_name: str
    claimant_name: str
    claimant_email: EmailStr
    evidence_text: str
    status: ClaimStatus
    admin_note: Optional[str] = None
    pickup_location: Optional[str] = None
    handover_status: Optional[HandoverStatus] = None
    has_unread_messages: bool = False
    created_at: datetime


class ClaimReviewIn(BaseModel):
    status: ClaimStatus
    admin_note: Optional[str] = Field(default=None, max_length=1000)
    # Required when approving: where the claimant collects the item.
    pickup_location: Optional[str] = Field(default=None, max_length=255)


class ClaimDetailOut(BaseModel):
    """A claim as seen by one of its participants. Never carries contact data."""

    id: str
    item_id: str
    item_name: str
    item_photo: Optional[HttpUrl] = None
    item_report_type: ReportType
    item_location: str
    item_status: ItemStatus
    status: ClaimStatus
    # Only the claimant and admins see the ownership evidence.
    evidence_text: Optional[str] = None
    admin_note: Optional[str] = None
    pickup_location: Optional[str] = None
    handover_status: Optional[HandoverStatus] = None
    collected_at: Optional[datetime] = None
    created_at: datetime
    my_role: ClaimRole
    can_message: bool
    can_confirm_collection: bool


class ClaimMessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class ClaimMessageOut(BaseModel):
    id: str
    sender_role: ClaimRole
    body: str
    is_mine: bool
    created_at: datetime

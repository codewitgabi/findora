from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from api.v1.models.claim import ClaimStatus


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
    created_at: datetime


class AdminClaimOut(BaseModel):
    id: str
    item_id: str
    item_name: str
    item_location: str
    claimant_name: str
    claimant_email: EmailStr
    evidence_text: str
    status: ClaimStatus
    created_at: datetime


class ClaimReviewIn(BaseModel):
    status: ClaimStatus
    admin_note: Optional[str] = Field(default=None, max_length=1000)

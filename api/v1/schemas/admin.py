from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from api.v1.models.item import HandedTo, ItemStatus, ReportType
from api.v1.models.user import AccountStatus, UserRole


class AdminStatsOut(BaseModel):
    pending_reports: int
    pending_claims: int
    flagged_items: int
    resolved_this_week: int
    awaiting_pickup: int = 0


class AdminReportOut(BaseModel):
    id: str
    item_name: str
    report_type: ReportType
    reporter_name: str
    location: str
    handed_to: Optional[HandedTo] = None
    created_at: datetime
    status: ItemStatus


class ReportStatusIn(BaseModel):
    status: ItemStatus
    note: Optional[str] = Field(default=None, max_length=1000)
    # With status "closed": the report this one duplicates.
    duplicate_of: Optional[str] = None


class AdminUserOut(BaseModel):
    id: str
    full_name: str
    email: EmailStr
    student_id: Optional[str] = None
    role: UserRole
    account_status: AccountStatus
    created_at: datetime
    report_count: int


class AdminUserUpdateIn(BaseModel):
    account_status: Optional[AccountStatus] = None
    # Only "user" and "officer" can be assigned here; admins are created by script.
    role: Optional[UserRole] = None

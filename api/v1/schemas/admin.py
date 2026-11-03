from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from api.v1.models.item import ItemStatus, ReportType
from api.v1.models.user import AccountStatus, UserRole


class AdminStatsOut(BaseModel):
    pending_reports: int
    pending_claims: int
    flagged_items: int
    resolved_this_week: int


class AdminReportOut(BaseModel):
    id: str
    item_name: str
    report_type: ReportType
    reporter_name: str
    location: str
    created_at: datetime
    status: ItemStatus


class ReportStatusIn(BaseModel):
    status: ItemStatus
    note: Optional[str] = Field(default=None, max_length=1000)


class AdminUserOut(BaseModel):
    id: str
    full_name: str
    email: EmailStr
    role: UserRole
    account_status: AccountStatus
    created_at: datetime
    report_count: int


class AdminUserUpdateIn(BaseModel):
    account_status: AccountStatus

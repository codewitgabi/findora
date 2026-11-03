from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.database import get_db
from api.response import success_response
from api.v1.dependencies.auth import require_admin
from api.v1.dependencies.pagination import PaginationDep
from api.v1.models.audit_log import AuditTargetType
from api.v1.models.claim import ClaimStatus
from api.v1.models.item import ItemStatus, ReportType
from api.v1.models.user import AccountStatus, UserRole
from api.v1.schemas.admin import (
    AdminReportOut,
    AdminStatsOut,
    AdminUserOut,
    AdminUserUpdateIn,
    ReportStatusIn,
)
from api.v1.schemas.audit_log import AuditLogOut
from api.v1.schemas.category import CategoryCreate, CategoryOut
from api.v1.schemas.claim import AdminClaimOut, ClaimReviewIn
from api.v1.services.admin import change_report_status, get_stats, list_reports
from api.v1.services.audit import list_audit_logs
from api.v1.services.categories import create_category, delete_category
from api.v1.services.claims import list_admin_claims, review_claim
from api.v1.services.users import list_admin_users, set_account_status
from api.v1.utils.mongo import paginated

# Every route in this router requires an admin; enforced server-side via the dependency.
router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(require_admin)])

Admin = Annotated[dict[str, Any], Depends(require_admin)]
Database = Annotated[AsyncIOMotorDatabase, Depends(get_db)]


@router.get("/stats")
async def stats(db: Database):
    data = AdminStatsOut(**await get_stats(db)).model_dump()
    return success_response("Stats retrieved", data=data)


@router.get("/reports")
async def reports(
    db: Database,
    pagination: PaginationDep,
    status: Optional[ItemStatus] = None,
    report_type: Optional[ReportType] = None,
    q: Optional[str] = None,
):
    rows, total = await list_reports(
        db, pagination, item_status=status, report_type=report_type, q=q
    )
    data = paginated(
        [AdminReportOut(**row).model_dump(mode="json") for row in rows], total, pagination
    )
    return success_response("Reports retrieved", data=data)


@router.patch("/reports/{report_id}/status")
async def update_report_status(
    report_id: str, payload: ReportStatusIn, admin: Admin, db: Database
):
    report = await change_report_status(db, admin, report_id, payload.status, payload.note)
    return success_response(
        "Report status updated", data=AdminReportOut(**report).model_dump(mode="json")
    )


@router.get("/claims")
async def claims(
    db: Database, pagination: PaginationDep, status: Optional[ClaimStatus] = None
):
    rows, total = await list_admin_claims(db, pagination, status)
    data = paginated(
        [AdminClaimOut(**row).model_dump(mode="json") for row in rows], total, pagination
    )
    return success_response("Claims retrieved", data=data)


@router.patch("/claims/{claim_id}")
async def update_claim(claim_id: str, payload: ClaimReviewIn, admin: Admin, db: Database):
    await review_claim(db, admin, claim_id, payload)
    return success_response("Claim updated")


@router.get("/users")
async def users(
    db: Database,
    pagination: PaginationDep,
    q: Optional[str] = None,
    role: Optional[UserRole] = None,
    account_status: Optional[AccountStatus] = None,
):
    rows, total = await list_admin_users(
        db, pagination, q=q, role=role, account_status=account_status
    )
    data = paginated(
        [AdminUserOut(**row).model_dump(mode="json") for row in rows], total, pagination
    )
    return success_response("Users retrieved", data=data)


@router.patch("/users/{user_id}")
async def update_user(user_id: str, payload: AdminUserUpdateIn, admin: Admin, db: Database):
    user = await set_account_status(db, admin, user_id, payload.account_status)
    return success_response(
        "User updated", data=AdminUserOut(**user).model_dump(mode="json")
    )


@router.post("/categories", status_code=status.HTTP_201_CREATED)
async def add_category(payload: CategoryCreate, admin: Admin, db: Database):
    category = await create_category(db, admin, payload.name)
    return success_response(
        "Category created",
        status.HTTP_201_CREATED,
        CategoryOut(**category).model_dump(mode="json"),
    )


@router.delete("/categories/{category_id}")
async def remove_category(category_id: str, admin: Admin, db: Database):
    await delete_category(db, admin, category_id)
    return success_response("Category deleted")


@router.get("/audit-logs")
async def audit_logs(
    db: Database,
    pagination: PaginationDep,
    target_type: Optional[AuditTargetType] = None,
):
    rows, total = await list_audit_logs(db, pagination, target_type)
    data = paginated(
        [AuditLogOut(**row).model_dump(mode="json") for row in rows], total, pagination
    )
    return success_response("Audit logs retrieved", data=data)

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.database import get_db
from api.response import success_response
from api.v1.dependencies.auth import get_current_user
from api.v1.dependencies.pagination import PaginationDep
from api.v1.schemas.claim import MyClaimOut
from api.v1.schemas.item import MyReportOut, MySummaryOut
from api.v1.schemas.notification import NotificationOut
from api.v1.schemas.user import ChangePasswordIn, UserOut, UserUpdateIn
from api.v1.services.claims import list_my_claims
from api.v1.services.items import list_my_reports, my_summary
from api.v1.services.notifications import list_notifications, mark_all_read, mark_read
from api.v1.services.users import change_password, update_profile
from api.v1.utils.mongo import paginated

router = APIRouter(prefix="/me", tags=["Me"])

CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]
Database = Annotated[AsyncIOMotorDatabase, Depends(get_db)]


@router.get("")
async def get_me(user: CurrentUser):
    return success_response("User retrieved", data=UserOut(**user).model_dump(mode="json"))


@router.patch("")
async def update_me(payload: UserUpdateIn, user: CurrentUser, db: Database):
    updated = await update_profile(db, user, payload)
    return success_response("Profile updated", data=UserOut(**updated).model_dump(mode="json"))


@router.post("/change-password")
async def change_my_password(payload: ChangePasswordIn, user: CurrentUser, db: Database):
    await change_password(db, user, payload)
    return success_response("Password changed successfully")


@router.get("/reports")
async def my_reports(user: CurrentUser, db: Database, pagination: PaginationDep):
    rows, total = await list_my_reports(db, user["id"], pagination)
    data = paginated(
        [MyReportOut(**row).model_dump(mode="json") for row in rows], total, pagination
    )
    return success_response("Reports retrieved", data=data)


@router.get("/summary")
async def summary(user: CurrentUser, db: Database):
    data = MySummaryOut(**await my_summary(db, user["id"])).model_dump()
    return success_response("Summary retrieved", data=data)


@router.get("/claims")
async def my_claims(user: CurrentUser, db: Database, pagination: PaginationDep):
    rows, total = await list_my_claims(db, user["id"], pagination)
    data = paginated(
        [MyClaimOut(**row).model_dump(mode="json") for row in rows], total, pagination
    )
    return success_response("Claims retrieved", data=data)


@router.get("/notifications")
async def my_notifications(user: CurrentUser, db: Database, pagination: PaginationDep):
    rows, total, unread = await list_notifications(db, user["id"], pagination)
    data = paginated(
        [NotificationOut(**row).model_dump(mode="json") for row in rows],
        total,
        pagination,
        unread_count=unread,
    )
    return success_response("Notifications retrieved", data=data)


@router.post("/notifications/read-all")
async def read_all_notifications(user: CurrentUser, db: Database):
    await mark_all_read(db, user["id"])
    return success_response("All notifications marked as read")


@router.patch("/notifications/{notification_id}/read")
async def read_notification(notification_id: str, user: CurrentUser, db: Database):
    await mark_read(db, user["id"], notification_id)
    return success_response("Notification marked as read")

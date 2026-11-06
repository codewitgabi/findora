from typing import Any, Optional

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.v1.dependencies.pagination import Pagination
from api.v1.models.audit_log import AuditTargetType
from api.v1.models.item import COLLECTION_NAME as ITEMS_COLLECTION
from api.v1.models.user import COLLECTION_NAME, AccountStatus, UserRole
from api.v1.schemas.user import ChangePasswordIn, UserUpdateIn
from api.v1.services.audit import record_audit
from api.v1.utils.errors import field_validation_error
from api.v1.utils.mongo import contains, serialize, to_object_id
from api.v1.utils.security import hash_password, verify_password


async def update_profile(
    db: AsyncIOMotorDatabase, user: dict[str, Any], payload: UserUpdateIn
) -> dict[str, Any]:
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "full_name" in changes:
        changes["full_name"] = changes["full_name"].strip()
        if not changes["full_name"]:
            raise field_validation_error("full_name", "Name must not be blank")
    if not changes:
        return user

    await db[COLLECTION_NAME].update_one({"_id": ObjectId(user["id"])}, {"$set": changes})
    return {**user, **changes}


async def change_password(
    db: AsyncIOMotorDatabase, user: dict[str, Any], payload: ChangePasswordIn
) -> None:
    if not verify_password(payload.current_password, user["password_hash"]):
        raise field_validation_error("current_password", "Current password is incorrect")

    await db[COLLECTION_NAME].update_one(
        {"_id": ObjectId(user["id"])},
        {"$set": {"password_hash": hash_password(payload.new_password)}},
    )


async def list_admin_users(
    db: AsyncIOMotorDatabase,
    pagination: Pagination,
    *,
    q: Optional[str] = None,
    role: Optional[UserRole] = None,
    account_status: Optional[AccountStatus] = None,
) -> tuple[list[dict[str, Any]], int]:
    query: dict[str, Any] = {}
    if q:
        pattern = contains(q)
        query["$or"] = [{"full_name": pattern}, {"email": pattern}]
    if role:
        query["role"] = role.value
    if account_status:
        query["account_status"] = account_status.value

    total = await db[COLLECTION_NAME].count_documents(query)
    users = [
        serialize(doc)
        async for doc in db[COLLECTION_NAME]
        .find(query)
        .sort("created_at", -1)
        .skip(pagination.skip)
        .limit(pagination.page_size)
    ]

    counts = {
        row["_id"]: row["n"]
        async for row in db[ITEMS_COLLECTION].aggregate(
            [
                {"$match": {"user_id": {"$in": [ObjectId(u["id"]) for u in users]}}},
                {"$group": {"_id": "$user_id", "n": {"$sum": 1}}},
            ]
        )
    }
    for user in users:
        user["report_count"] = counts.get(ObjectId(user["id"]), 0)
    return users, total


async def update_user_access(
    db: AsyncIOMotorDatabase,
    admin: dict[str, Any],
    user_id: str,
    *,
    new_status: Optional[AccountStatus] = None,
    new_role: Optional[UserRole] = None,
) -> dict[str, Any]:
    if new_status is None and new_role is None:
        raise field_validation_error("account_status", "Send account_status and/or role")
    target = await _get_target(db, user_id)
    if new_role is not None:
        target = await _set_role(db, admin, target, new_role)
    if new_status is not None:
        target = await set_account_status(db, admin, user_id, new_status)
    report_count = await db[ITEMS_COLLECTION].count_documents({"user_id": ObjectId(target["id"])})
    return {**target, "report_count": report_count}


async def _get_target(db: AsyncIOMotorDatabase, user_id: str) -> dict[str, Any]:
    doc = await db[COLLECTION_NAME].find_one({"_id": to_object_id(user_id, resource="User")})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return serialize(doc)


async def _set_role(
    db: AsyncIOMotorDatabase, admin: dict[str, Any], target: dict[str, Any], role: UserRole
) -> dict[str, Any]:
    if role == UserRole.ADMIN or target["role"] == UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator roles are managed with the create_admin script",
        )
    if target["role"] == role.value:
        return target
    await db[COLLECTION_NAME].update_one(
        {"_id": ObjectId(target["id"])},
        # New role takes effect on the next request; revoke tokens so stale UIs refresh.
        {"$set": {"role": role.value}, "$inc": {"token_version": 1}},
    )
    await record_audit(
        db,
        admin,
        action=(
            f"Made {target['full_name']} a lost-property officer"
            if role == UserRole.OFFICER
            else f"Removed officer role from {target['full_name']}"
        ),
        target_type=AuditTargetType.USER,
        target_id=target["id"],
    )
    return {**target, "role": role.value}


async def set_account_status(
    db: AsyncIOMotorDatabase,
    admin: dict[str, Any],
    user_id: str,
    new_status: AccountStatus,
) -> dict[str, Any]:
    target = await _get_target(db, user_id)
    doc = {"_id": ObjectId(target["id"])}
    if target["role"] == UserRole.ADMIN.value and new_status == AccountStatus.SUSPENDED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator accounts cannot be suspended",
        )

    await db[COLLECTION_NAME].update_one(
        {"_id": doc["_id"]}, {"$set": {"account_status": new_status.value}}
    )
    await record_audit(
        db,
        admin,
        action=(
            f"{'Suspended' if new_status == AccountStatus.SUSPENDED else 'Reactivated'} "
            f"user {target['full_name']}"
        ),
        target_type=AuditTargetType.USER,
        target_id=target["id"],
    )

    report_count = await db[ITEMS_COLLECTION].count_documents({"user_id": doc["_id"]})
    return {**target, "account_status": new_status.value, "report_count": report_count}

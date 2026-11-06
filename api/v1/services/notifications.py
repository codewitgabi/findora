from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.v1.dependencies.pagination import Pagination
from api.v1.models.notification import COLLECTION_NAME, NotificationType
from api.v1.utils.mongo import serialize, to_object_id


async def create_notification(
    db: AsyncIOMotorDatabase,
    user_id: str | ObjectId,
    *,
    type: NotificationType,
    title: str,
    message: str,
    item_id: str | ObjectId | None = None,
    claim_id: str | ObjectId | None = None,
) -> None:
    """Store an in-app notification.

    ``item_id`` / ``claim_id`` let the client link the notification to the page it is
    about (the item detail or the claim thread).
    """
    await db[COLLECTION_NAME].insert_one(
        {
            "user_id": ObjectId(user_id),
            "type": type.value,
            "title": title,
            "message": message,
            "item_id": ObjectId(item_id) if item_id else None,
            "claim_id": ObjectId(claim_id) if claim_id else None,
            "is_read": False,
            "created_at": datetime.now(timezone.utc),
        }
    )


async def list_notifications(
    db: AsyncIOMotorDatabase, user_id: str, pagination: Pagination
) -> tuple[list[dict[str, Any]], int, int]:
    """Return ``(items, total, unread_count)`` for the user, newest first."""
    owner = {"user_id": ObjectId(user_id)}
    total = await db[COLLECTION_NAME].count_documents(owner)
    unread = await db[COLLECTION_NAME].count_documents({**owner, "is_read": False})
    cursor = (
        db[COLLECTION_NAME]
        .find(owner)
        .sort("created_at", -1)
        .skip(pagination.skip)
        .limit(pagination.page_size)
    )
    return [serialize(doc) async for doc in cursor], total, unread


async def mark_read(db: AsyncIOMotorDatabase, user_id: str, notification_id: str) -> None:
    result = await db[COLLECTION_NAME].update_one(
        {
            "_id": to_object_id(notification_id, resource="Notification"),
            "user_id": ObjectId(user_id),
        },
        {"$set": {"is_read": True}},
    )
    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
        )


async def mark_all_read(db: AsyncIOMotorDatabase, user_id: str) -> None:
    await db[COLLECTION_NAME].update_many(
        {"user_id": ObjectId(user_id), "is_read": False}, {"$set": {"is_read": True}}
    )

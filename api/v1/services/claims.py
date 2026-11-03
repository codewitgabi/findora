from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.v1.dependencies.pagination import Pagination
from api.v1.models.audit_log import AuditTargetType
from api.v1.models.claim import COLLECTION_NAME, ClaimStatus
from api.v1.models.item import COLLECTION_NAME as ITEMS_COLLECTION
from api.v1.models.item import PUBLIC_STATUSES, ItemStatus
from api.v1.models.notification import NotificationType
from api.v1.models.user import COLLECTION_NAME as USERS_COLLECTION
from api.v1.schemas.claim import ClaimReviewIn
from api.v1.services.audit import record_audit
from api.v1.services.items import get_item, set_item_status
from api.v1.services.notifications import create_notification
from api.v1.utils.errors import field_validation_error
from api.v1.utils.mongo import fetch_by_ids, serialize, to_object_id


async def create_claim(
    db: AsyncIOMotorDatabase, user: dict[str, Any], item_id: str, evidence_text: str
) -> dict[str, Any]:
    item = await get_item(db, item_id)
    if item["status"] not in PUBLIC_STATUSES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    if item["user_id"] == user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot claim your own report",
        )

    existing = await db[COLLECTION_NAME].find_one(
        {
            "item_id": ObjectId(item_id),
            "user_id": ObjectId(user["id"]),
            "status": ClaimStatus.PENDING.value,
        }
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an open claim on this item",
        )

    document = {
        "item_id": ObjectId(item_id),
        "user_id": ObjectId(user["id"]),
        "evidence_text": evidence_text.strip(),
        "status": ClaimStatus.PENDING.value,
        "admin_note": None,
        "reviewed_by": None,
        "reviewed_at": None,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db[COLLECTION_NAME].insert_one(document)
    document["_id"] = result.inserted_id
    return serialize(document)


async def list_my_claims(
    db: AsyncIOMotorDatabase, user_id: str, pagination: Pagination
) -> tuple[list[dict[str, Any]], int]:
    owner = {"user_id": ObjectId(user_id)}
    total = await db[COLLECTION_NAME].count_documents(owner)
    claims = [
        doc
        async for doc in db[COLLECTION_NAME]
        .find(owner)
        .sort("created_at", -1)
        .skip(pagination.skip)
        .limit(pagination.page_size)
    ]
    items = await fetch_by_ids(db, ITEMS_COLLECTION, (c["item_id"] for c in claims))

    rows = []
    for claim in claims:
        item = items.get(claim["item_id"], {})
        rows.append(
            {
                "id": str(claim["_id"]),
                "item_id": str(claim["item_id"]),
                "item_name": item.get("item_name", "Removed item"),
                "item_location": item.get("location", ""),
                "evidence_text": claim["evidence_text"],
                "status": claim["status"],
                "admin_note": claim.get("admin_note"),
                "created_at": claim["created_at"],
            }
        )
    return rows, total


async def list_admin_claims(
    db: AsyncIOMotorDatabase,
    pagination: Pagination,
    claim_status: Optional[ClaimStatus] = None,
) -> tuple[list[dict[str, Any]], int]:
    query: dict[str, Any] = {"status": claim_status.value} if claim_status else {}
    total = await db[COLLECTION_NAME].count_documents(query)
    claims = [
        doc
        async for doc in db[COLLECTION_NAME]
        .find(query)
        .sort("created_at", -1)
        .skip(pagination.skip)
        .limit(pagination.page_size)
    ]
    items = await fetch_by_ids(db, ITEMS_COLLECTION, (c["item_id"] for c in claims))
    users = await fetch_by_ids(db, USERS_COLLECTION, (c["user_id"] for c in claims))

    rows = []
    for claim in claims:
        item = items.get(claim["item_id"], {})
        claimant = users.get(claim["user_id"], {})
        rows.append(
            {
                "id": str(claim["_id"]),
                "item_id": str(claim["item_id"]),
                "item_name": item.get("item_name", "Removed item"),
                "item_location": item.get("location", ""),
                "claimant_name": claimant.get("full_name", "Deleted user"),
                "claimant_email": claimant.get("email", "unknown@example.com"),
                "evidence_text": claim["evidence_text"],
                "status": claim["status"],
                "created_at": claim["created_at"],
            }
        )
    return rows, total


async def review_claim(
    db: AsyncIOMotorDatabase,
    admin: dict[str, Any],
    claim_id: str,
    payload: ClaimReviewIn,
) -> None:
    if payload.status == ClaimStatus.PENDING:
        raise field_validation_error("status", "Status must be 'approved' or 'rejected'")

    now = datetime.now(timezone.utc)
    claim = await db[COLLECTION_NAME].find_one_and_update(
        {
            "_id": to_object_id(claim_id, resource="Claim"),
            "status": ClaimStatus.PENDING.value,
        },
        {
            "$set": {
                "status": payload.status.value,
                "admin_note": payload.admin_note,
                "reviewed_by": ObjectId(admin["id"]),
                "reviewed_at": now,
            }
        },
    )
    if not claim:
        exists = await db[COLLECTION_NAME].count_documents({"_id": ObjectId(claim_id)}, limit=1)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT if exists else status.HTTP_404_NOT_FOUND,
            detail="This claim has already been reviewed" if exists else "Claim not found",
        )

    item = await get_item(db, str(claim["item_id"]))
    approved = payload.status == ClaimStatus.APPROVED

    await create_notification(
        db,
        claim["user_id"],
        type=NotificationType.CLAIM,
        title="Claim approved" if approved else "Claim rejected",
        message=(
            f"Your claim on '{item['item_name']}' was "
            f"{'approved' if approved else 'rejected'}."
            + (f" {payload.admin_note}" if payload.admin_note else "")
        ),
    )

    if approved:
        await _close_item_after_approval(db, item, approved_claim_id=claim["_id"], now=now, admin=admin)

    await record_audit(
        db,
        admin,
        action=f"{'Approved' if approved else 'Rejected'} claim on '{item['item_name']}'",
        target_type=AuditTargetType.CLAIM,
        target_id=claim_id,
    )


async def _close_item_after_approval(
    db: AsyncIOMotorDatabase,
    item: dict[str, Any],
    *,
    approved_claim_id: ObjectId,
    now: datetime,
    admin: dict[str, Any],
) -> None:
    """Mark the item as handed over and reject every competing pending claim."""
    if item["status"] != ItemStatus.RESOLVED.value:
        await set_item_status(db, item, ItemStatus.RESOLVED)

    competing = db[COLLECTION_NAME].find(
        {
            "item_id": ObjectId(item["id"]),
            "status": ClaimStatus.PENDING.value,
            "_id": {"$ne": approved_claim_id},
        }
    )
    async for other in competing:
        await db[COLLECTION_NAME].update_one(
            {"_id": other["_id"]},
            {
                "$set": {
                    "status": ClaimStatus.REJECTED.value,
                    "admin_note": "Another claim on this item was approved.",
                    "reviewed_by": ObjectId(admin["id"]),
                    "reviewed_at": now,
                }
            },
        )
        await create_notification(
            db,
            other["user_id"],
            type=NotificationType.CLAIM,
            title="Claim rejected",
            message=f"Your claim on '{item['item_name']}' was rejected because another claim was approved.",
        )

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.v1.dependencies.pagination import Pagination
from api.v1.models.audit_log import AuditTargetType
from api.v1.models.claim import COLLECTION_NAME as CLAIMS_COLLECTION
from api.v1.models.claim import ClaimStatus
from api.v1.models.item import COLLECTION_NAME as ITEMS_COLLECTION
from api.v1.models.item import ItemStatus, ReportType
from api.v1.models.user import COLLECTION_NAME as USERS_COLLECTION
from api.v1.services.audit import record_audit
from api.v1.services.items import get_item, set_item_status
from api.v1.utils.mongo import contains, fetch_by_ids

# Allowed report status transitions available to admins.
_TRANSITIONS: dict[ItemStatus, set[ItemStatus]] = {
    ItemStatus.PENDING: {ItemStatus.ACTIVE, ItemStatus.REJECTED},
    ItemStatus.ACTIVE: {ItemStatus.RESOLVED},
    ItemStatus.MATCHED: {ItemStatus.RESOLVED},
}

_AUDIT_VERBS = {
    ItemStatus.ACTIVE: "Approved",
    ItemStatus.REJECTED: "Rejected",
    ItemStatus.RESOLVED: "Marked as resolved",
}


async def get_stats(db: AsyncIOMotorDatabase) -> dict[str, int]:
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    contested = await db[CLAIMS_COLLECTION].aggregate(
        [
            {"$match": {"status": ClaimStatus.PENDING.value}},
            {"$group": {"_id": "$item_id", "n": {"$sum": 1}}},
            {"$match": {"n": {"$gte": 2}}},
            {"$count": "total"},
        ]
    ).to_list(1)

    return {
        "pending_reports": await db[ITEMS_COLLECTION].count_documents(
            {"status": ItemStatus.PENDING.value}
        ),
        "pending_claims": await db[CLAIMS_COLLECTION].count_documents(
            {"status": ClaimStatus.PENDING.value}
        ),
        # An item with several pending claims needs a closer look from an admin.
        "flagged_items": contested[0]["total"] if contested else 0,
        "resolved_this_week": await db[ITEMS_COLLECTION].count_documents(
            {"status": ItemStatus.RESOLVED.value, "resolved_at": {"$gte": week_ago}}
        ),
    }


async def list_reports(
    db: AsyncIOMotorDatabase,
    pagination: Pagination,
    *,
    item_status: Optional[ItemStatus] = None,
    report_type: Optional[ReportType] = None,
    q: Optional[str] = None,
) -> tuple[list[dict[str, Any]], int]:
    query: dict[str, Any] = {}
    if item_status:
        query["status"] = item_status.value
    if report_type:
        query["report_type"] = report_type.value
    if q:
        pattern = contains(q)
        query["$or"] = [{"item_name": pattern}, {"description": pattern}]

    total = await db[ITEMS_COLLECTION].count_documents(query)
    reports = [
        doc
        async for doc in db[ITEMS_COLLECTION]
        .find(query)
        .sort("created_at", -1)
        .skip(pagination.skip)
        .limit(pagination.page_size)
    ]
    reporters = await fetch_by_ids(db, USERS_COLLECTION, (r["user_id"] for r in reports))

    rows = [
        {
            "id": str(report["_id"]),
            "item_name": report["item_name"],
            "report_type": report["report_type"],
            "reporter_name": reporters.get(report["user_id"], {}).get("full_name", "Deleted user"),
            "location": report["location"],
            "created_at": report["created_at"],
            "status": report["status"],
        }
        for report in reports
    ]
    return rows, total


async def change_report_status(
    db: AsyncIOMotorDatabase,
    admin: dict[str, Any],
    report_id: str,
    new_status: ItemStatus,
    note: Optional[str],
) -> dict[str, Any]:
    item = await get_item(db, report_id)
    current = ItemStatus(item["status"])
    if new_status not in _TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A {current.value} report cannot be changed to {new_status.value}",
        )

    await set_item_status(db, item, new_status, note=note)
    await record_audit(
        db,
        admin,
        action=f"{_AUDIT_VERBS[new_status]} {item['report_type']} report '{item['item_name']}'",
        target_type=AuditTargetType.REPORT,
        target_id=item["id"],
    )

    reporter = await db[USERS_COLLECTION].find_one({"_id": ObjectId(item["user_id"])})
    refreshed = await get_item(db, report_id)
    return {
        "id": refreshed["id"],
        "item_name": refreshed["item_name"],
        "report_type": refreshed["report_type"],
        "reporter_name": reporter["full_name"] if reporter else "Deleted user",
        "location": refreshed["location"],
        "created_at": refreshed["created_at"],
        "status": refreshed["status"],
    }


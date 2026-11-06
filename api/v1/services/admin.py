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
from api.v1.models.item import CloseReason, ItemStatus, ReportType
from api.v1.models.user import COLLECTION_NAME as USERS_COLLECTION
from api.v1.models.notification import NotificationType
from api.v1.services.audit import record_audit
from api.v1.services.notifications import create_notification
from api.v1.utils.errors import field_validation_error
from api.v1.services.claims import confirm_collection
from api.v1.services.items import get_item, retire_item, set_item_status
from api.v1.utils.mongo import contains, fetch_by_ids

# Allowed report status transitions available to admins.
# CLOSED removes an inappropriate or duplicate report.
_TRANSITIONS: dict[ItemStatus, set[ItemStatus]] = {
    ItemStatus.PENDING: {ItemStatus.ACTIVE, ItemStatus.REJECTED, ItemStatus.CLOSED},
    ItemStatus.ACTIVE: {ItemStatus.RESOLVED, ItemStatus.CLOSED},
    ItemStatus.MATCHED: {ItemStatus.RESOLVED, ItemStatus.CLOSED},
    # Resolving an item awaiting pickup confirms the approved claim's collection.
    ItemStatus.CLAIMED: {ItemStatus.RESOLVED},
}

_AUDIT_VERBS = {
    ItemStatus.ACTIVE: "Approved",
    ItemStatus.REJECTED: "Rejected",
    ItemStatus.RESOLVED: "Marked as resolved",
    ItemStatus.CLOSED: "Removed",
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
        "awaiting_pickup": await db[ITEMS_COLLECTION].count_documents(
            {"status": ItemStatus.CLAIMED.value}
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
            "handed_to": report.get("handed_to"),
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
    duplicate_of: Optional[str] = None,
) -> dict[str, Any]:
    item = await get_item(db, report_id)
    current = ItemStatus(item["status"])
    if new_status not in _TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A {current.value} report cannot be changed to {new_status.value}",
        )
    if duplicate_of and new_status != ItemStatus.CLOSED:
        raise field_validation_error("duplicate_of", "Only a removal can mark a duplicate")

    original = None
    if duplicate_of:
        if duplicate_of == item["id"]:
            raise field_validation_error("duplicate_of", "A report can't duplicate itself")
        try:
            original = await get_item(db, duplicate_of)
        except HTTPException:
            raise field_validation_error("duplicate_of", "That report doesn't exist") from None

    if new_status == ItemStatus.CLOSED:
        await _remove_report(db, admin, item, note=note, original=original)
        await record_audit(
            db,
            admin,
            action=f"Removed {item['report_type']} report '{item['item_name']}'"
            + (f" as a duplicate of '{original['item_name']}'" if original else ""),
            target_type=AuditTargetType.REPORT,
            target_id=item["id"],
            details=note,
        )
        return await _report_row(db, report_id)

    if current == ItemStatus.CLAIMED:
        # Close through the claim so the claimant's linked reports resolve too.
        approved = await db[CLAIMS_COLLECTION].find_one(
            {"item_id": ObjectId(item["id"]), "status": ClaimStatus.APPROVED.value},
            sort=[("reviewed_at", -1)],
        )
        if approved:
            await confirm_collection(db, admin, str(approved["_id"]))
        else:
            await set_item_status(db, item, new_status, note=note)
    else:
        await set_item_status(db, item, new_status, note=note)
        if new_status == ItemStatus.RESOLVED:
            # Resolved outside the claim flow: nobody should be left waiting on it.
            await retire_item(
                db,
                item,
                claim_note="An administrator resolved this report.",
                match_reason="was resolved",
                reviewer_id=admin["id"],
            )
    await record_audit(
        db,
        admin,
        action=f"{_AUDIT_VERBS[new_status]} {item['report_type']} report '{item['item_name']}'",
        target_type=AuditTargetType.REPORT,
        target_id=item["id"],
        details=note,
    )
    return await _report_row(db, report_id)


async def _remove_report(
    db: AsyncIOMotorDatabase,
    admin: dict[str, Any],
    item: dict[str, Any],
    *,
    note: Optional[str],
    original: Optional[dict[str, Any]],
) -> None:
    """Close an inappropriate or duplicate report and tell its reporter why."""
    now = datetime.now(timezone.utc)
    reason = CloseReason.DUPLICATE if original else CloseReason.REMOVED_BY_ADMIN
    await db[ITEMS_COLLECTION].update_one(
        {"_id": ObjectId(item["id"])},
        {
            "$set": {
                "status": ItemStatus.CLOSED.value,
                "close_reason": reason.value,
                "close_note": note,
                "closed_by": "admin",
                "closed_at": now,
                "updated_at": now,
                "duplicate_of": ObjectId(original["id"]) if original else None,
            }
        },
    )
    await retire_item(
        db,
        item,
        claim_note="An administrator removed this report.",
        match_reason="was removed by an administrator",
        reviewer_id=admin["id"],
    )
    if original:
        message = (
            f"Your report '{item['item_name']}' was closed as a duplicate of "
            f"'{original['item_name']}'."
        )
    else:
        message = f"Your report '{item['item_name']}' was removed by an administrator."
    if note:
        message = f"{message} Note: {note}"
    await create_notification(
        db,
        item["user_id"],
        type=NotificationType.STATUS,
        title="Report closed",
        message=message,
        # Point a duplicate at the report that stays open.
        item_id=original["id"] if original else item["id"],
    )


async def _report_row(db: AsyncIOMotorDatabase, report_id: str) -> dict[str, Any]:
    refreshed = await get_item(db, report_id)
    reporter = await db[USERS_COLLECTION].find_one({"_id": ObjectId(refreshed["user_id"])})
    return {
        "id": refreshed["id"],
        "item_name": refreshed["item_name"],
        "report_type": refreshed["report_type"],
        "reporter_name": reporter["full_name"] if reporter else "Deleted user",
        "location": refreshed["location"],
        "handed_to": refreshed.get("handed_to"),
        "created_at": refreshed["created_at"],
        "status": refreshed["status"],
    }


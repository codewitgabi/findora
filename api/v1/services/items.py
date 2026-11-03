from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.v1.dependencies.pagination import Pagination
from api.v1.models.claim import COLLECTION_NAME as CLAIMS_COLLECTION
from api.v1.models.claim import ClaimStatus
from api.v1.models.item import (
    COLLECTION_NAME,
    PUBLIC_STATUSES,
    ItemStatus,
    ReportType,
)
from api.v1.models.notification import NotificationType
from api.v1.models.user import UserRole
from api.v1.services.categories import resolve_category
from api.v1.services.images import get_image_hash
from api.v1.services.matching import (
    MATCH_THRESHOLD,
    MIN_SEARCH_SCORE,
    MIN_SIMILAR_SCORE,
    item_pair_score,
    search_score,
)
from api.v1.services.notifications import create_notification
from api.v1.utils.mongo import contains, exact_ci, serialize, to_object_id

# Upper bound on candidates scored in memory for photo search / similarity.
MAX_CANDIDATES = 500
SIMILAR_ITEMS_LIMIT = 5


@dataclass
class SearchFilters:
    q: Optional[str] = None
    category: Optional[str] = None
    color: Optional[str] = None
    location: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    report_type: Optional[ReportType] = None
    status: Optional[ItemStatus] = None


# --------------------------------------------------------------------------- #
# Creation
# --------------------------------------------------------------------------- #


async def create_item(
    db: AsyncIOMotorDatabase,
    user_id: str,
    report_type: ReportType,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """Insert a new report in ``pending`` state, fingerprinting its photo."""
    document = {
        **fields,
        "category": await resolve_category(db, fields["category"]),
        "report_type": report_type.value,
        "user_id": ObjectId(user_id),
        "status": ItemStatus.PENDING.value,
        "image_hash": await get_image_hash(db, fields["photo"]),
        "created_at": datetime.now(timezone.utc),
    }
    result = await db[COLLECTION_NAME].insert_one(document)
    document["_id"] = result.inserted_id
    return serialize(document)


# --------------------------------------------------------------------------- #
# Status changes and matching
# --------------------------------------------------------------------------- #

_STATUS_MESSAGES = {
    ItemStatus.ACTIVE: ("Report approved", "Your report '{name}' was approved and is now visible."),
    ItemStatus.REJECTED: ("Report rejected", "Your report '{name}' was not approved."),
    ItemStatus.RESOLVED: ("Report resolved", "Your report '{name}' was marked as resolved."),
}


async def get_item(db: AsyncIOMotorDatabase, item_id: str) -> dict[str, Any]:
    doc = await db[COLLECTION_NAME].find_one(
        {"_id": to_object_id(item_id, resource="Item")}
    )
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return serialize(doc)


async def set_item_status(
    db: AsyncIOMotorDatabase,
    item: dict[str, Any],
    new_status: ItemStatus,
    *,
    note: Optional[str] = None,
) -> None:
    """Persist a status change and notify the reporter.

    Approving a report also triggers matching against the opposite report type.
    """
    changes: dict[str, Any] = {"status": new_status.value}
    if new_status == ItemStatus.RESOLVED:
        changes["resolved_at"] = datetime.now(timezone.utc)
    await db[COLLECTION_NAME].update_one({"_id": ObjectId(item["id"])}, {"$set": changes})

    title, template = _STATUS_MESSAGES[new_status]
    message = template.format(name=item["item_name"])
    if note:
        message = f"{message} Note: {note}"
    await create_notification(
        db, item["user_id"], type=NotificationType.STATUS, title=title, message=message
    )

    if new_status == ItemStatus.ACTIVE:
        await match_item(db, {**item, "status": new_status.value})


async def match_item(db: AsyncIOMotorDatabase, item: dict[str, Any]) -> None:
    """Flag possible matches for a newly approved report and notify both parties.

    Matches are only ever *possible*; both reports are marked ``matched`` so the
    UI can surface them, and no contact details are shared.
    """
    candidates = db[COLLECTION_NAME].find(
        _opposite_public_query(item), limit=MAX_CANDIDATES
    )
    async for raw in candidates:
        other = serialize(raw)
        if other["user_id"] == item["user_id"]:
            continue
        if item_pair_score(item, other) < MATCH_THRESHOLD:
            continue

        for mine, theirs in ((item, other), (other, item)):
            await create_notification(
                db,
                mine["user_id"],
                type=NotificationType.MATCH,
                title="New match found",
                message=(
                    f"A {theirs['report_type']} report may match your "
                    f"'{mine['item_name']}'. Review it to learn more."
                ),
            )
        await db[COLLECTION_NAME].update_many(
            {
                "_id": {"$in": [ObjectId(item["id"]), ObjectId(other["id"])]},
                "status": ItemStatus.ACTIVE.value,
            },
            {"$set": {"status": ItemStatus.MATCHED.value}},
        )


def _opposite_public_query(item: dict[str, Any]) -> dict[str, Any]:
    opposite = (
        ReportType.FOUND if item["report_type"] == ReportType.LOST else ReportType.LOST
    )
    return {"report_type": opposite.value, "status": {"$in": list(PUBLIC_STATUSES)}}


async def find_similar(
    db: AsyncIOMotorDatabase, item: dict[str, Any]
) -> list[dict[str, Any]]:
    scored = []
    async for raw in db[COLLECTION_NAME].find(
        _opposite_public_query(item), limit=MAX_CANDIDATES
    ):
        other = serialize(raw)
        score = item_pair_score(item, other)
        if score >= MIN_SIMILAR_SCORE:
            scored.append(
                {
                    "id": other["id"],
                    "item_name": other["item_name"],
                    "location": other["location"],
                    "score": round(score, 2),
                }
            )
    scored.sort(key=lambda s: s["score"], reverse=True)
    return scored[:SIMILAR_ITEMS_LIMIT]


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #


async def get_item_detail(
    db: AsyncIOMotorDatabase, item_id: str, user: dict[str, Any]
) -> dict[str, Any]:
    """Item detail for a viewer. Contact details are never part of the result."""
    item = await get_item(db, item_id)
    is_owner = item["user_id"] == user["id"]

    claim = await db[CLAIMS_COLLECTION].find_one(
        {"item_id": ObjectId(item["id"]), "user_id": ObjectId(user["id"])},
        sort=[("created_at", -1)],
    )

    can_view = (
        item["status"] in PUBLIC_STATUSES
        or is_owner
        or claim is not None
        or user["role"] == UserRole.ADMIN.value
    )
    if not can_view:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    similar = await find_similar(db, item) if item["status"] in PUBLIC_STATUSES else []
    return {
        **item,
        "is_owner": is_owner,
        "similar_items": similar,
        "my_claim": {"id": str(claim["_id"]), "status": claim["status"]} if claim else None,
    }


def _search_query(filters: SearchFilters) -> dict[str, Any]:
    """Mongo filter for public search. Only approved, unresolved items qualify."""
    statuses = [s for s in PUBLIC_STATUSES if not filters.status or s == filters.status.value]
    query: dict[str, Any] = {"status": {"$in": statuses}}

    if filters.report_type:
        query["report_type"] = filters.report_type.value
    if filters.category:
        query["category"] = exact_ci(filters.category)
    if filters.color:
        query["color"] = exact_ci(filters.color)
    if filters.location:
        query["location"] = contains(filters.location)
    if filters.date_from or filters.date_to:
        date_range: dict[str, str] = {}
        if filters.date_from:
            date_range["$gte"] = filters.date_from.isoformat()
        if filters.date_to:
            date_range["$lte"] = filters.date_to.isoformat()
        query["date"] = date_range
    if filters.q:
        pattern = contains(filters.q)
        query["$or"] = [
            {field: pattern}
            for field in ("item_name", "description", "category", "color", "location")
        ]
    return query


def _to_search_result(item: dict[str, Any], score: Optional[float]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "item_name": item["item_name"],
        "report_type": item["report_type"],
        "location": item["location"],
        "date": item["date"],
        "photo": item["photo"],
        "score": round(score, 2) if score is not None else None,
    }


async def search_items(
    db: AsyncIOMotorDatabase, filters: SearchFilters, pagination: Pagination
) -> tuple[list[dict[str, Any]], int]:
    query = _search_query(filters)
    total = await db[COLLECTION_NAME].count_documents(query)
    cursor = (
        db[COLLECTION_NAME]
        .find(query)
        .sort("created_at", -1)
        .skip(pagination.skip)
        .limit(pagination.page_size)
    )
    return [_to_search_result(serialize(doc), None) async for doc in cursor], total


async def search_items_by_image(
    db: AsyncIOMotorDatabase,
    query_hash: str,
    filters: SearchFilters,
    pagination: Pagination,
) -> tuple[list[dict[str, Any]], int]:
    """Rank candidates by hybrid score (image similarity + metadata agreement)."""
    cursor = (
        db[COLLECTION_NAME]
        .find(_search_query(filters))
        .sort("created_at", -1)
        .limit(MAX_CANDIDATES)
    )
    anchor = filters.date_to or filters.date_from

    ranked = []
    async for doc in cursor:
        item = serialize(doc)
        score = search_score(
            query_hash,
            item,
            category=filters.category,
            color=filters.color,
            location=filters.location,
            anchor_date=anchor.isoformat() if anchor else None,
        )
        if score >= MIN_SEARCH_SCORE:
            ranked.append(_to_search_result(item, score))

    ranked.sort(key=lambda r: r["score"], reverse=True)
    page = ranked[pagination.skip : pagination.skip + pagination.page_size]
    return page, len(ranked)


async def list_my_reports(
    db: AsyncIOMotorDatabase, user_id: str, pagination: Pagination
) -> tuple[list[dict[str, Any]], int]:
    owner = {"user_id": ObjectId(user_id)}
    total = await db[COLLECTION_NAME].count_documents(owner)
    cursor = (
        db[COLLECTION_NAME]
        .find(owner)
        .sort("created_at", -1)
        .skip(pagination.skip)
        .limit(pagination.page_size)
    )
    items = []
    async for doc in cursor:
        item = serialize(doc)
        items.append(
            {
                "id": item["id"],
                "report_type": item["report_type"],
                "item_name": item["item_name"],
                "last_seen_or_found_location": item["location"],
                "status": item["status"],
                "created_at": item["created_at"],
            }
        )
    return items, total


async def my_summary(db: AsyncIOMotorDatabase, user_id: str) -> dict[str, int]:
    owner = {"user_id": ObjectId(user_id)}
    return {
        "my_reports": await db[COLLECTION_NAME].count_documents(owner),
        "active_matches": await db[COLLECTION_NAME].count_documents(
            {**owner, "status": ItemStatus.MATCHED.value}
        ),
        "claims_pending": await db[CLAIMS_COLLECTION].count_documents(
            {**owner, "status": ClaimStatus.PENDING.value}
        ),
    }

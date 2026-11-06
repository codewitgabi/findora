from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.v1.dependencies.pagination import Pagination
from api.v1.models.claim import COLLECTION_NAME as CLAIMS_COLLECTION
from api.v1.models.claim import ClaimStatus, HandoverStatus
from api.v1.models.item import (
    COLLECTION_NAME,
    OPEN_STATUSES,
    PUBLIC_STATUSES,
    CloseReason,
    ItemStatus,
    ReportType,
)
from api.v1.models.notification import NotificationType
from api.v1.models.user import STAFF_ROLES
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
from api.v1.utils.errors import field_validation_error
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
    """Insert a new report in ``pending`` state, fingerprinting its photo (if any)."""
    now = datetime.now(timezone.utc)
    photo = fields.get("photo")
    document = {
        **fields,
        "category": await resolve_category(db, fields["category"]),
        "report_type": report_type.value,
        "user_id": ObjectId(user_id),
        "status": ItemStatus.PENDING.value,
        "image_hash": await get_image_hash(db, photo) if photo else None,
        "created_at": now,
        "updated_at": now,
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
    ItemStatus.CLAIMED: ("Claim approved", "A claim on your report '{name}' was approved."),
    ItemStatus.CLOSED: ("Report closed", "Your report '{name}' was closed by an administrator."),
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
    notify: bool = True,
) -> None:
    """Persist a status change and (unless ``notify`` is false) notify the reporter.

    Callers that send a richer, context-specific notification themselves pass
    ``notify=False``. Approving a report also triggers matching against the opposite
    report type.
    """
    now = datetime.now(timezone.utc)
    changes: dict[str, Any] = {"status": new_status.value, "updated_at": now}
    if new_status == ItemStatus.RESOLVED:
        changes["resolved_at"] = now
    await db[COLLECTION_NAME].update_one({"_id": ObjectId(item["id"])}, {"$set": changes})

    if notify:
        title, template = _STATUS_MESSAGES[new_status]
        message = template.format(name=item["item_name"])
        if note:
            message = f"{message} Note: {note}"
        await create_notification(
            db,
            item["user_id"],
            type=NotificationType.STATUS,
            title=title,
            message=message,
            item_id=item["id"],
        )

    if new_status == ItemStatus.ACTIVE:
        await match_item(db, {**item, "status": new_status.value})


async def match_item(db: AsyncIOMotorDatabase, item: dict[str, Any]) -> None:
    """Flag possible matches for a newly approved report and notify both parties.

    Matches are only ever *possible*; both reports are marked ``matched`` and linked
    to each other through ``matched_with`` so each owner can open the other report.
    No contact details are shared.
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
                item_id=theirs["id"],
            )
        for mine, theirs in ((item, other), (other, item)):
            await db[COLLECTION_NAME].update_one(
                {"_id": ObjectId(mine["id"])},
                {"$addToSet": {"matched_with": ObjectId(theirs["id"])}},
            )
        await db[COLLECTION_NAME].update_many(
            {
                "_id": {"$in": [ObjectId(item["id"]), ObjectId(other["id"])]},
                "status": ItemStatus.ACTIVE.value,
            },
            {"$set": {"status": ItemStatus.MATCHED.value, "updated_at": datetime.now(timezone.utc)}},
        )


async def linked_open_reports(
    db: AsyncIOMotorDatabase, item: dict[str, Any], user_id: str
) -> list[dict[str, Any]]:
    """``user_id``'s still-open reports that matching linked to ``item``."""
    linked = item.get("matched_with") or []
    if not linked:
        return []
    cursor = db[COLLECTION_NAME].find(
        {
            "_id": {"$in": linked},
            "user_id": ObjectId(user_id),
            "status": {"$in": list(PUBLIC_STATUSES)},
        }
    )
    return [serialize(doc) async for doc in cursor]


async def release_matches(
    db: AsyncIOMotorDatabase,
    item: dict[str, Any],
    *,
    keep_user_id: Optional[str] = None,
    reason: str = "was claimed by someone else",
    notify: bool = True,
) -> None:
    """Unlink ``item`` from other people's reports once it leaves the public pool.

    Called when a claim on ``item`` is approved, or when ``item`` is resolved, closed
    or sent back for review. Reports owned by ``keep_user_id`` (the claimant) are
    handled by the claim flow. Every other linked owner is told the possible match is
    gone (unless ``notify`` is false), and their report drops back to ``active`` when
    it has no other open match left.
    """
    linked = item.get("matched_with") or []
    if not linked:
        return
    item_oid = ObjectId(item["id"])
    await db[COLLECTION_NAME].update_one({"_id": item_oid}, {"$set": {"matched_with": []}})
    async for raw in db[COLLECTION_NAME].find({"_id": {"$in": linked}}):
        other = serialize(raw)
        if other["user_id"] == keep_user_id or other["status"] not in PUBLIC_STATUSES:
            continue

        remaining = [oid for oid in (raw.get("matched_with") or []) if oid != item_oid]
        still_matched = bool(remaining) and await db[COLLECTION_NAME].count_documents(
            {"_id": {"$in": remaining}, "status": {"$in": list(PUBLIC_STATUSES)}}, limit=1
        )
        changes: dict[str, Any] = {"$pull": {"matched_with": item_oid}}
        if other["status"] == ItemStatus.MATCHED.value and not still_matched:
            changes["$set"] = {
                "status": ItemStatus.ACTIVE.value,
                "updated_at": datetime.now(timezone.utc),
            }
        await db[COLLECTION_NAME].update_one({"_id": raw["_id"]}, changes)

        if notify:
            await create_notification(
                db,
                other["user_id"],
                type=NotificationType.MATCH,
                title="Possible match no longer available",
                message=(
                    f"A {item['report_type']} report that may have matched your "
                    f"'{other['item_name']}' {reason}. Your report stays open and we'll "
                    "let you know about new matches."
                ),
                item_id=other["id"],
            )


async def reject_pending_claims(
    db: AsyncIOMotorDatabase,
    item: dict[str, Any],
    *,
    note: str,
    reviewer_id: Optional[str] = None,
) -> int:
    """Reject every pending claim on ``item`` and tell each claimant why."""
    now = datetime.now(timezone.utc)
    rejected = 0
    async for claim in db[CLAIMS_COLLECTION].find(
        {"item_id": ObjectId(item["id"]), "status": ClaimStatus.PENDING.value}
    ):
        await db[CLAIMS_COLLECTION].update_one(
            {"_id": claim["_id"], "status": ClaimStatus.PENDING.value},
            {
                "$set": {
                    "status": ClaimStatus.REJECTED.value,
                    "admin_note": note,
                    "reviewed_by": ObjectId(reviewer_id) if reviewer_id else None,
                    "reviewed_at": now,
                }
            },
        )
        await create_notification(
            db,
            claim["user_id"],
            type=NotificationType.CLAIM,
            title="Claim closed",
            message=f"Your claim on '{item['item_name']}' was closed. {note}",
            item_id=item["id"],
            claim_id=claim["_id"],
        )
        rejected += 1
    return rejected


async def retire_item(
    db: AsyncIOMotorDatabase,
    item: dict[str, Any],
    *,
    claim_note: str,
    match_reason: str,
    reviewer_id: Optional[str] = None,
) -> None:
    """Tidy up after ``item`` leaves the open pool without a claim being approved.

    Pending claims are rejected and linked reports are released, so nobody is left
    waiting on a report that no longer exists.
    """
    await reject_pending_claims(db, item, note=claim_note, reviewer_id=reviewer_id)
    await release_matches(db, item, reason=match_reason)


# --------------------------------------------------------------------------- #
# Owner edits and closing
# --------------------------------------------------------------------------- #

# Editing these on an approved report doesn't send it back for review.
_REVIEW_FREE_FIELDS = {"handed_to", "condition", "identifying_marks"}
_FIELDS_BY_TYPE = {
    ReportType.LOST.value: {
        "item_name", "category", "color", "description", "photo", "location", "date",
        "identifying_marks",
    },
    ReportType.FOUND.value: {
        "item_name", "category", "color", "description", "photo", "location", "date",
        "condition", "handed_to",
    },
}

_CLOSE_MESSAGES = {
    CloseReason.FOUND_IT: "The reporter found the item themselves.",
    CloseReason.NO_LONGER_NEEDED: "The reporter closed the report.",
    CloseReason.OTHER: "The reporter closed the report.",
}


async def _owned_open_item(
    db: AsyncIOMotorDatabase, user: dict[str, Any], item_id: str
) -> dict[str, Any]:
    item = await get_item(db, item_id)
    if item["user_id"] != user["id"]:
        # Same answer as a missing item, so other people's reports aren't probed.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    if item["status"] not in OPEN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A {item['status']} report can no longer be changed",
        )
    return item


async def update_item(
    db: AsyncIOMotorDatabase, user: dict[str, Any], item_id: str, changes: dict[str, Any]
) -> dict[str, Any]:
    """Apply an owner's edits.

    Changing what the item is (name, photo, description...) on an approved report
    sends it back to ``pending`` so an admin re-reviews it, and unlinks its matches.
    Edits are refused while claims on the report are under review.
    """
    item = await _owned_open_item(db, user, item_id)
    allowed = _FIELDS_BY_TYPE[item["report_type"]]
    unknown = set(changes) - allowed
    if unknown:
        field = sorted(unknown)[0]
        raise field_validation_error(field, f"'{field}' can't be set on a {item['report_type']} report")

    if "category" in changes:
        changes["category"] = await resolve_category(db, changes["category"])
    if "identifying_marks" in changes:
        changes["identifying_marks"] = (changes["identifying_marks"] or "").strip() or None
    if "photo" in changes:
        if item["report_type"] == ReportType.FOUND.value and not changes["photo"]:
            raise field_validation_error("photo", "Found reports need a photo")
        changes["image_hash"] = (
            await get_image_hash(db, changes["photo"]) if changes["photo"] else None
        )

    changed = {k: v for k, v in changes.items() if item.get(k) != v}
    if not changed:
        return item

    if await db[CLAIMS_COLLECTION].count_documents(
        {"item_id": ObjectId(item["id"]), "status": ClaimStatus.PENDING.value}, limit=1
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This report has claims under review, so it can't be edited right now",
        )

    needs_review = (
        item["status"] in PUBLIC_STATUSES
        and bool(set(changed) - _REVIEW_FREE_FIELDS - {"image_hash"})
    )
    changed["updated_at"] = datetime.now(timezone.utc)
    if needs_review:
        changed["status"] = ItemStatus.PENDING.value
    await db[COLLECTION_NAME].update_one({"_id": ObjectId(item["id"])}, {"$set": changed})
    if needs_review:
        await release_matches(db, item, notify=False)
    return await get_item(db, item_id)


async def close_item(
    db: AsyncIOMotorDatabase,
    user: dict[str, Any],
    item_id: str,
    reason: CloseReason,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """The owner withdraws their report (for example because they found it)."""
    if reason not in _CLOSE_MESSAGES:
        raise field_validation_error("reason", "Choose found_it, no_longer_needed or other")
    item = await _owned_open_item(db, user, item_id)
    now = datetime.now(timezone.utc)
    await db[COLLECTION_NAME].update_one(
        {"_id": ObjectId(item["id"])},
        {
            "$set": {
                "status": ItemStatus.CLOSED.value,
                "close_reason": reason.value,
                "close_note": (note or "").strip() or None,
                "closed_by": "owner",
                "closed_at": now,
                "updated_at": now,
            }
        },
    )
    await retire_item(
        db,
        item,
        claim_note=_CLOSE_MESSAGES[reason],
        match_reason="was closed by its reporter",
    )
    return await get_item(db, item_id)


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

    is_admin = user["role"] in STAFF_ROLES
    can_view = item["status"] in PUBLIC_STATUSES or is_owner or claim is not None or is_admin
    if not can_view:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    # Owners see possible matches straight away, even while their report awaits review.
    show_similar = item["status"] in PUBLIC_STATUSES or (
        item["status"] == ItemStatus.PENDING.value and (is_owner or is_admin)
    )
    similar = await find_similar(db, item) if show_similar else []

    # Reports that matching linked to this one, so the owner can act on a match.
    matched_items: list[dict[str, Any]] = []
    if (is_owner or is_admin) and item.get("matched_with"):
        async for raw in db[COLLECTION_NAME].find(
            {"_id": {"$in": item["matched_with"]}, "status": {"$in": list(PUBLIC_STATUSES)}}
        ):
            matched_items.append(
                {
                    "id": str(raw["_id"]),
                    "item_name": raw["item_name"],
                    "report_type": raw["report_type"],
                    "location": raw["location"],
                    "status": raw["status"],
                }
            )

    # The reporter needs the approved claim to coordinate the handover.
    handover = None
    if is_owner or is_admin:
        approved = await db[CLAIMS_COLLECTION].find_one(
            {"item_id": ObjectId(item["id"]), "status": ClaimStatus.APPROVED.value},
            sort=[("reviewed_at", -1)],
        )
        if approved:
            handover = {
                "claim_id": str(approved["_id"]),
                "pickup_location": approved.get("pickup_location"),
                "handover_status": handover_status(approved, item),
            }

    my_claim = None
    if claim:
        my_claim = {
            "id": str(claim["_id"]),
            "status": claim["status"],
            "pickup_location": claim.get("pickup_location"),
            "handover_status": handover_status(claim, item),
        }

    return {
        **item,
        "handed_to": item.get("handed_to"),
        # Private verification detail: never shown to other users.
        "identifying_marks": item.get("identifying_marks") if (is_owner or is_admin) else None,
        "updated_at": item.get("updated_at"),
        "close_reason": item.get("close_reason"),
        "is_owner": is_owner,
        "similar_items": similar,
        "matched_items": matched_items,
        "handover": handover,
        "my_claim": my_claim,
    }


def handover_status(claim: dict[str, Any], item: dict[str, Any]) -> Optional[str]:
    """``awaiting_pickup`` / ``collected`` for approved claims, otherwise ``None``.

    Claims approved before the handover step existed resolved their item straight
    away, so an approved claim without ``collected_at`` on a non-``claimed`` item
    counts as collected.
    """
    if claim["status"] != ClaimStatus.APPROVED.value:
        return None
    if claim.get("collected_at") or item.get("status") != ItemStatus.CLAIMED.value:
        return HandoverStatus.COLLECTED.value
    return HandoverStatus.AWAITING_PICKUP.value


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

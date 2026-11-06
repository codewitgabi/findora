from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.v1.dependencies.pagination import Pagination
from api.v1.models.audit_log import AuditTargetType
from api.v1.models.claim import (
    COLLECTION_NAME,
    MESSAGES_COLLECTION_NAME,
    ClaimRole,
    ClaimStatus,
    HandoverStatus,
)
from api.v1.models.item import COLLECTION_NAME as ITEMS_COLLECTION
from api.v1.models.item import PUBLIC_STATUSES, HandedTo, ItemStatus
from api.v1.models.notification import NotificationType
from api.v1.models.user import COLLECTION_NAME as USERS_COLLECTION
from api.v1.models.user import STAFF_ROLES
from api.v1.schemas.claim import ClaimReviewIn
from api.v1.services.audit import record_audit
from api.v1.services.items import (
    get_item,
    handover_status,
    linked_open_reports,
    release_matches,
    set_item_status,
)
from api.v1.services.notifications import create_notification
from api.v1.utils.errors import field_validation_error
from api.v1.utils.mongo import fetch_by_ids, serialize, to_object_id

# Longest message preview copied into a notification.
_PREVIEW_CHARS = 140
# Upper bound on messages returned for one claim thread.
_MAX_MESSAGES = 500


# --------------------------------------------------------------------------- #
# Creating and listing claims
# --------------------------------------------------------------------------- #


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
        "pickup_location": None,
        "linked_item_ids": [],
        "collected_at": None,
        "collected_by_role": None,
        "admin_unread": True,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db[COLLECTION_NAME].insert_one(document)
    document["_id"] = result.inserted_id

    # Let the reporter know someone came forward. No claimant identity is shared.
    await create_notification(
        db,
        item["user_id"],
        type=NotificationType.CLAIM,
        title="New claim on your report",
        message=(
            f"Someone submitted a claim on your report '{item['item_name']}'. "
            "An administrator is reviewing it, and we'll tell you the outcome."
        ),
        item_id=item["id"],
    )
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
                "pickup_location": claim.get("pickup_location"),
                "handover_status": handover_status(claim, item),
                "collected_at": claim.get("collected_at"),
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
    user_ids = [c["user_id"] for c in claims] + [
        i["user_id"] for i in items.values() if i.get("user_id")
    ]
    users = await fetch_by_ids(db, USERS_COLLECTION, user_ids)

    rows = []
    for claim in claims:
        item = items.get(claim["item_id"], {})
        claimant = users.get(claim["user_id"], {})
        reporter = users.get(item.get("user_id"), {})
        rows.append(
            {
                "id": str(claim["_id"]),
                "item_id": str(claim["item_id"]),
                "item_name": item.get("item_name", "Removed item"),
                "item_location": item.get("location", ""),
                "item_report_type": item.get("report_type"),
                "item_handed_to": item.get("handed_to"),
                "reporter_name": reporter.get("full_name", "Deleted user"),
                "claimant_name": claimant.get("full_name", "Deleted user"),
                "claimant_email": claimant.get("email", "unknown@example.com"),
                "evidence_text": claim["evidence_text"],
                "status": claim["status"],
                "admin_note": claim.get("admin_note"),
                "pickup_location": claim.get("pickup_location"),
                "handover_status": handover_status(claim, item),
                "has_unread_messages": bool(claim.get("admin_unread")),
                "created_at": claim["created_at"],
            }
        )
    return rows, total


# --------------------------------------------------------------------------- #
# Admin review
# --------------------------------------------------------------------------- #


def default_pickup_location(item: dict[str, Any]) -> Optional[str]:
    """Where a found item is held, when the finder handed it to an office."""
    handed_to = item.get("handed_to")
    if not handed_to or handed_to == HandedTo.STILL_HAVE_IT.value:
        return None
    return handed_to


async def review_claim(
    db: AsyncIOMotorDatabase,
    admin: dict[str, Any],
    claim_id: str,
    payload: ClaimReviewIn,
) -> None:
    if payload.status == ClaimStatus.PENDING:
        raise field_validation_error("status", "Status must be 'approved' or 'rejected'")

    approved = payload.status == ClaimStatus.APPROVED
    pickup_location = (payload.pickup_location or "").strip() or None
    if approved and not pickup_location:
        raise field_validation_error(
            "pickup_location", "Tell the claimant where to collect the item"
        )

    now = datetime.now(timezone.utc)
    changes: dict[str, Any] = {
        "status": payload.status.value,
        "admin_note": payload.admin_note,
        "reviewed_by": ObjectId(admin["id"]),
        "reviewed_at": now,
    }
    if approved:
        changes["pickup_location"] = pickup_location

    claim = await db[COLLECTION_NAME].find_one_and_update(
        {
            "_id": to_object_id(claim_id, resource="Claim"),
            "status": ClaimStatus.PENDING.value,
        },
        {"$set": changes},
    )
    if not claim:
        exists = await db[COLLECTION_NAME].count_documents({"_id": ObjectId(claim_id)}, limit=1)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT if exists else status.HTTP_404_NOT_FOUND,
            detail="This claim has already been reviewed" if exists else "Claim not found",
        )

    item = await get_item(db, str(claim["item_id"]))

    if approved:
        await _hold_item_for_pickup(
            db,
            item,
            claim=claim,
            pickup_location=pickup_location,
            admin_note=payload.admin_note,
            now=now,
            admin=admin,
        )
    else:
        await create_notification(
            db,
            claim["user_id"],
            type=NotificationType.CLAIM,
            title="Claim rejected",
            message=f"Your claim on '{item['item_name']}' was rejected."
            + (f" {payload.admin_note}" if payload.admin_note else ""),
            item_id=item["id"],
            claim_id=claim["_id"],
        )

    details = "; ".join(
        part
        for part in (
            f"Pickup: {pickup_location}" if approved else None,
            f"Note: {payload.admin_note}" if payload.admin_note else None,
        )
        if part
    )
    await record_audit(
        db,
        admin,
        action=f"{'Approved' if approved else 'Rejected'} claim on '{item['item_name']}'",
        target_type=AuditTargetType.CLAIM,
        target_id=claim_id,
        details=details or None,
    )


async def _hold_item_for_pickup(
    db: AsyncIOMotorDatabase,
    item: dict[str, Any],
    *,
    claim: dict[str, Any],
    pickup_location: str,
    admin_note: Optional[str],
    now: datetime,
    admin: dict[str, Any],
) -> None:
    """Take the item off the public pool until the claimant collects it.

    Rejects competing claims, sets the claimant's own linked reports aside so they
    close together on collection, and tells everyone involved what happens next.
    """
    claimant_id = str(claim["user_id"])
    await set_item_status(db, item, ItemStatus.CLAIMED, notify=False)

    own_reports = await linked_open_reports(db, item, claimant_id)
    if own_reports:
        await db[COLLECTION_NAME].update_one(
            {"_id": claim["_id"]},
            {"$set": {"linked_item_ids": [ObjectId(r["id"]) for r in own_reports]}},
        )
        await db[ITEMS_COLLECTION].update_many(
            {"_id": {"$in": [ObjectId(r["id"]) for r in own_reports]}},
            {"$set": {"status": ItemStatus.CLAIMED.value}},
        )
    await release_matches(db, item, keep_user_id=claimant_id)

    note = f" {admin_note}" if admin_note else ""
    await create_notification(
        db,
        claimant_id,
        type=NotificationType.CLAIM,
        title="Claim approved: ready for pickup",
        message=(
            f"Your claim on '{item['item_name']}' was approved. Collect it at: "
            f"{pickup_location}.{note} Confirm in the app once you have it."
        ),
        item_id=item["id"],
        claim_id=claim["_id"],
    )
    reporter_ask = (
        "Please arrange the handover through the claim thread."
        if item.get("handed_to") == HandedTo.STILL_HAVE_IT.value
        else "No action is needed unless the admin contacts you."
    )
    await create_notification(
        db,
        item["user_id"],
        type=NotificationType.CLAIM,
        title="Claim on your report approved",
        message=(
            f"An administrator approved a claim on your report '{item['item_name']}'. "
            f"Pickup location: {pickup_location}. {reporter_ask}"
        ),
        item_id=item["id"],
        claim_id=claim["_id"],
    )

    competing = db[COLLECTION_NAME].find(
        {
            "item_id": ObjectId(item["id"]),
            "status": ClaimStatus.PENDING.value,
            "_id": {"$ne": claim["_id"]},
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
            item_id=item["id"],
            claim_id=other["_id"],
        )


# --------------------------------------------------------------------------- #
# Participants: detail, collection, messages
# --------------------------------------------------------------------------- #


def _role_for(user: dict[str, Any], claim: dict[str, Any], item: dict[str, Any]) -> Optional[ClaimRole]:
    """The viewer's role on this claim, or ``None`` when they may not see it.

    The reporter only joins once the claim is approved, so pending evidence and
    rejected claims stay between the claimant and admins.
    """
    if str(claim["user_id"]) == user["id"]:
        return ClaimRole.CLAIMANT
    if item.get("user_id") == user["id"] and claim["status"] == ClaimStatus.APPROVED.value:
        return ClaimRole.REPORTER
    if user["role"] in STAFF_ROLES:
        return ClaimRole.ADMIN
    return None


async def _load_for_participant(
    db: AsyncIOMotorDatabase, user: dict[str, Any], claim_id: str
) -> tuple[dict[str, Any], dict[str, Any], ClaimRole]:
    claim = await db[COLLECTION_NAME].find_one({"_id": to_object_id(claim_id, resource="Claim")})
    if not claim:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    item = await get_item(db, str(claim["item_id"]))
    role = _role_for(user, claim, item)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    return claim, item, role


def _can_message(claim: dict[str, Any], item: dict[str, Any], role: ClaimRole) -> bool:
    if claim["status"] == ClaimStatus.PENDING.value:
        return role != ClaimRole.REPORTER
    return handover_status(claim, item) == HandoverStatus.AWAITING_PICKUP.value


async def get_claim_detail(
    db: AsyncIOMotorDatabase, user: dict[str, Any], claim_id: str
) -> dict[str, Any]:
    claim, item, role = await _load_for_participant(db, user, claim_id)
    handover = handover_status(claim, item)
    return {
        "id": str(claim["_id"]),
        "item_id": item["id"],
        "item_name": item["item_name"],
        "item_photo": item.get("photo"),
        "item_report_type": item["report_type"],
        "item_location": item["location"],
        "item_status": item["status"],
        "status": claim["status"],
        "evidence_text": claim["evidence_text"] if role != ClaimRole.REPORTER else None,
        "admin_note": claim.get("admin_note"),
        "pickup_location": claim.get("pickup_location"),
        "handover_status": handover,
        "collected_at": claim.get("collected_at"),
        "created_at": claim["created_at"],
        "my_role": role.value,
        "can_message": _can_message(claim, item, role),
        "can_confirm_collection": handover == HandoverStatus.AWAITING_PICKUP.value,
    }


async def confirm_collection(
    db: AsyncIOMotorDatabase, user: dict[str, Any], claim_id: str
) -> None:
    """Record that the item changed hands and close everything tied to the claim.

    Any participant can confirm: the claimant ("I have it"), the reporter ("I handed
    it over") or an admin.
    """
    claim, item, role = await _load_for_participant(db, user, claim_id)
    if handover_status(claim, item) != HandoverStatus.AWAITING_PICKUP.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This claim is not awaiting pickup",
        )

    now = datetime.now(timezone.utc)
    updated = await db[COLLECTION_NAME].update_one(
        {"_id": claim["_id"], "collected_at": None},
        {"$set": {"collected_at": now, "collected_by_role": role.value}},
    )
    if updated.modified_count == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Collection was already confirmed",
        )

    await set_item_status(db, item, ItemStatus.RESOLVED, notify=False)
    for linked_id in claim.get("linked_item_ids") or []:
        linked = await db[ITEMS_COLLECTION].find_one({"_id": linked_id})
        if linked and linked["status"] == ItemStatus.CLAIMED.value:
            await set_item_status(db, serialize(linked), ItemStatus.RESOLVED, notify=False)

    who = {
        ClaimRole.CLAIMANT: "the claimant",
        ClaimRole.REPORTER: "the reporter",
        ClaimRole.ADMIN: "an administrator",
    }[role]
    closed_own = " Your matching report was closed too." if claim.get("linked_item_ids") else ""
    recipients = {
        str(claim["user_id"]): f"Collection of '{item['item_name']}' was confirmed by {who}.{closed_own}",
        item["user_id"]: (
            f"'{item['item_name']}' was handed over to its claimant (confirmed by {who}). "
            "Your report is now resolved. Thank you!"
        ),
    }
    for recipient, message in recipients.items():
        if recipient == user["id"]:
            continue
        await create_notification(
            db,
            recipient,
            type=NotificationType.CLAIM,
            title="Item collected",
            message=message,
            item_id=item["id"],
            claim_id=claim["_id"],
        )

    if role == ClaimRole.ADMIN:
        await record_audit(
            db,
            user,
            action=f"Confirmed collection of '{item['item_name']}'",
            target_type=AuditTargetType.CLAIM,
            target_id=str(claim["_id"]),
        )


async def list_messages(
    db: AsyncIOMotorDatabase, user: dict[str, Any], claim_id: str
) -> list[dict[str, Any]]:
    claim, _, role = await _load_for_participant(db, user, claim_id)
    if role == ClaimRole.ADMIN and claim.get("admin_unread"):
        await db[COLLECTION_NAME].update_one(
            {"_id": claim["_id"]}, {"$set": {"admin_unread": False}}
        )

    cursor = (
        db[MESSAGES_COLLECTION_NAME]
        .find({"claim_id": claim["_id"]})
        .sort("created_at", 1)
        .limit(_MAX_MESSAGES)
    )
    return [
        {
            "id": str(doc["_id"]),
            "sender_role": doc["sender_role"],
            "body": doc["body"],
            "is_mine": str(doc["sender_id"]) == user["id"],
            "created_at": doc["created_at"],
        }
        async for doc in cursor
    ]


async def post_message(
    db: AsyncIOMotorDatabase, user: dict[str, Any], claim_id: str, body: str
) -> dict[str, Any]:
    claim, item, role = await _load_for_participant(db, user, claim_id)
    if not _can_message(claim, item, role):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This conversation is closed",
        )

    body = body.strip()
    if not body:
        raise field_validation_error("body", "Message cannot be empty")

    now = datetime.now(timezone.utc)
    document = {
        "claim_id": claim["_id"],
        "sender_id": ObjectId(user["id"]),
        "sender_role": role.value,
        "body": body,
        "created_at": now,
    }
    result = await db[MESSAGES_COLLECTION_NAME].insert_one(document)
    await db[COLLECTION_NAME].update_one(
        {"_id": claim["_id"]},
        {"$set": {"last_message_at": now, "admin_unread": role != ClaimRole.ADMIN}},
    )

    # Admins see unread threads on the claims queue; the other parties get a notification.
    sender_label = {
        ClaimRole.CLAIMANT: "The claimant",
        ClaimRole.REPORTER: "The reporter",
        ClaimRole.ADMIN: "An administrator",
    }[role]
    preview = body if len(body) <= _PREVIEW_CHARS else body[: _PREVIEW_CHARS - 1] + "…"
    recipients = {str(claim["user_id"])}
    if claim["status"] == ClaimStatus.APPROVED.value:
        recipients.add(item["user_id"])
    recipients.discard(user["id"])
    for recipient in recipients:
        await create_notification(
            db,
            recipient,
            type=NotificationType.MESSAGE,
            title=f"New message about '{item['item_name']}'",
            message=f"{sender_label}: {preview}",
            item_id=item["id"],
            claim_id=claim["_id"],
        )

    return {
        "id": str(result.inserted_id),
        "sender_role": role.value,
        "body": body,
        "is_mine": True,
        "created_at": now,
    }

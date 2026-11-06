from datetime import datetime, timedelta, timezone

from bson import ObjectId

from api.v1.services.retention import purge_expired_records


async def test_purge_removes_old_finished_cases_and_read_notifications(db):
    now = datetime.now(timezone.utc)
    old, recent = now - timedelta(days=400), now - timedelta(days=10)
    user = ObjectId()

    def report(status, updated_at, **extra):
        return {"user_id": user, "item_name": status, "status": status, "created_at": updated_at,
                "updated_at": updated_at, **extra}

    items = await db["Items"].insert_many([
        report("resolved", old),
        report("closed", old),
        report("rejected", recent),
        report("active", old),            # still open: kept however old
        {"user_id": user, "item_name": "legacy", "status": "resolved", "created_at": old},  # no updated_at
    ])
    resolved_id, closed_id, recent_id, open_id, legacy_id = items.inserted_ids
    claim = await db["Claims"].insert_one({"item_id": resolved_id, "user_id": user, "status": "approved"})
    await db["Claims"].insert_one({"item_id": open_id, "user_id": user, "status": "pending"})
    await db["ClaimMessages"].insert_one({"claim_id": claim.inserted_id, "body": "hi", "created_at": old})
    await db["Notifications"].insert_many([
        {"user_id": user, "is_read": True, "created_at": old},
        {"user_id": user, "is_read": False, "created_at": old},
        {"user_id": user, "is_read": True, "created_at": recent},
    ])
    await db["AuditLogs"].insert_one({"action": "Approved claim", "created_at": old})

    counts = await purge_expired_records(db, days=365, now=now)
    assert counts == {"items": 3, "claims": 1, "messages": 1, "notifications": 1}
    remaining = {doc["_id"] async for doc in db["Items"].find()}
    assert remaining == {recent_id, open_id}
    assert await db["Claims"].count_documents({}) == 1
    assert await db["Notifications"].count_documents({}) == 2
    assert await db["AuditLogs"].count_documents({}) == 1  # the case record is kept
    assert resolved_id not in remaining and closed_id not in remaining and legacy_id not in remaining

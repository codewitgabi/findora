import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from api.v1.models.claim import COLLECTION_NAME as CLAIMS_COLLECTION
from api.v1.models.claim import MESSAGES_COLLECTION_NAME
from api.v1.models.item import COLLECTION_NAME as ITEMS_COLLECTION
from api.v1.models.item import ItemStatus
from api.v1.models.notification import COLLECTION_NAME as NOTIFICATIONS_COLLECTION
from api.v1.utils.config import config
from api.v1.utils.logger import get_logger

logger = get_logger("retention")

# Reports in these states are finished and can be purged once old enough.
_FINISHED = [ItemStatus.RESOLVED.value, ItemStatus.CLOSED.value, ItemStatus.REJECTED.value]
_PURGE_INTERVAL_SECONDS = 24 * 60 * 60


async def purge_expired_records(
    db: AsyncIOMotorDatabase, *, days: int, now: Optional[datetime] = None
) -> dict[str, int]:
    """Delete finished reports (with their claims and messages) and read notifications
    last touched more than ``days`` ago. The audit log is kept as the case record.
    """
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    old_items = {
        "status": {"$in": _FINISHED},
        "$or": [
            {"updated_at": {"$lt": cutoff}},
            {"updated_at": {"$exists": False}, "created_at": {"$lt": cutoff}},
        ],
    }
    item_ids = [doc["_id"] async for doc in db[ITEMS_COLLECTION].find(old_items, {"_id": 1})]
    claim_ids = [
        doc["_id"]
        async for doc in db[CLAIMS_COLLECTION].find({"item_id": {"$in": item_ids}}, {"_id": 1})
    ]

    messages = await db[MESSAGES_COLLECTION_NAME].delete_many({"claim_id": {"$in": claim_ids}})
    claims = await db[CLAIMS_COLLECTION].delete_many({"_id": {"$in": claim_ids}})
    items = await db[ITEMS_COLLECTION].delete_many({"_id": {"$in": item_ids}})
    notifications = await db[NOTIFICATIONS_COLLECTION].delete_many(
        {"is_read": True, "created_at": {"$lt": cutoff}}
    )
    counts = {
        "items": items.deleted_count,
        "claims": claims.deleted_count,
        "messages": messages.deleted_count,
        "notifications": notifications.deleted_count,
    }
    logger.info("Retention purge finished", extra={"cutoff": cutoff.isoformat(), **counts})
    return counts


async def run_retention_loop(db: AsyncIOMotorDatabase) -> None:
    """Purge once at startup and then daily. Disabled when RETENTION_DAYS is 0."""
    if config.RETENTION_DAYS <= 0:
        return
    while True:
        try:
            await purge_expired_records(db, days=config.RETENTION_DAYS)
        except Exception:  # noqa: BLE001 - a failed purge must never take the API down
            logger.exception("Retention purge failed")
        await asyncio.sleep(_PURGE_INTERVAL_SECONDS)

from datetime import datetime, timezone
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from api.v1.dependencies.pagination import Pagination
from api.v1.models.audit_log import COLLECTION_NAME, AuditTargetType
from api.v1.utils.mongo import serialize


async def record_audit(
    db: AsyncIOMotorDatabase,
    admin: dict[str, Any],
    *,
    action: str,
    target_type: AuditTargetType,
    target_id: str,
    details: Optional[str] = None,
) -> None:
    """Append an entry to the audit log. The log is append-only by design."""
    await db[COLLECTION_NAME].insert_one(
        {
            "admin_id": admin["id"],
            "admin_name": admin["full_name"],
            "action": action,
            "target_type": target_type.value,
            "target_id": str(target_id),
            "details": details,
            "created_at": datetime.now(timezone.utc),
        }
    )


async def list_audit_logs(
    db: AsyncIOMotorDatabase,
    pagination: Pagination,
    target_type: Optional[AuditTargetType] = None,
) -> tuple[list[dict[str, Any]], int]:
    query: dict[str, Any] = {"target_type": target_type.value} if target_type else {}
    total = await db[COLLECTION_NAME].count_documents(query)
    cursor = (
        db[COLLECTION_NAME]
        .find(query)
        .sort("created_at", -1)
        .skip(pagination.skip)
        .limit(pagination.page_size)
    )
    return [serialize(doc) async for doc in cursor], total

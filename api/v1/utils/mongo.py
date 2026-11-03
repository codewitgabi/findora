import re
from typing import Any, Iterable

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.v1.dependencies.pagination import Pagination


def serialize(document: dict[str, Any]) -> dict[str, Any]:
    """Rename ``_id`` to ``id`` and stringify every ObjectId reference."""
    serialized = dict(document)
    serialized["id"] = str(serialized.pop("_id"))
    for key, value in serialized.items():
        if isinstance(value, ObjectId):
            serialized[key] = str(value)
    return serialized


def to_object_id(value: str, *, resource: str = "Resource") -> ObjectId:
    """Parse a path id, answering 404 (not 500) for malformed ids."""
    if not ObjectId.is_valid(value):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource} not found"
        )
    return ObjectId(value)


def contains(text: str) -> dict[str, Any]:
    """Case-insensitive 'contains' regex filter with user input escaped."""
    return {"$regex": re.escape(text.strip()), "$options": "i"}


def exact_ci(text: str) -> dict[str, Any]:
    """Case-insensitive exact-match regex filter with user input escaped."""
    return {"$regex": f"^{re.escape(text.strip())}$", "$options": "i"}


def paginated(
    items: list[dict[str, Any]], total: int, pagination: Pagination, **extra: Any
) -> dict[str, Any]:
    return {
        "items": items,
        "total": total,
        "page": pagination.page,
        "page_size": pagination.page_size,
        **extra,
    }


async def fetch_by_ids(
    db: AsyncIOMotorDatabase, collection: str, ids: Iterable[ObjectId]
) -> dict[ObjectId, dict[str, Any]]:
    """Load documents for a page of results in one query, keyed by ``_id``."""
    unique_ids = list(set(ids))
    if not unique_ids:
        return {}
    cursor = db[collection].find({"_id": {"$in": unique_ids}})
    return {doc["_id"]: doc async for doc in cursor}

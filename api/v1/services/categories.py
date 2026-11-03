from typing import Any

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from api.v1.models.audit_log import AuditTargetType
from api.v1.models.category import COLLECTION_NAME, DEFAULT_CATEGORIES
from api.v1.models.item import COLLECTION_NAME as ITEMS_COLLECTION
from api.v1.services.audit import record_audit
from api.v1.utils.errors import field_validation_error
from api.v1.utils.mongo import serialize, to_object_id


async def seed_categories(db: AsyncIOMotorDatabase) -> None:
    """Insert the default categories that are missing. Safe to run on every startup."""
    for name in DEFAULT_CATEGORIES:
        await db[COLLECTION_NAME].update_one(
            {"name_lower": name.lower()},
            {"$setOnInsert": {"name": name, "name_lower": name.lower()}},
            upsert=True,
        )


async def resolve_category(db: AsyncIOMotorDatabase, name: str) -> str:
    """Map a submitted category name to its canonical spelling or reject it with 422."""
    doc = await db[COLLECTION_NAME].find_one({"name_lower": name.strip().lower()})
    if not doc:
        raise field_validation_error("category", "Unknown category")
    return doc["name"]


async def list_categories(
    db: AsyncIOMotorDatabase, *, with_counts: bool = False
) -> list[dict[str, Any]]:
    cursor = db[COLLECTION_NAME].find().sort("name_lower", 1)
    categories = [serialize(doc) async for doc in cursor]
    if with_counts:
        counts = {
            row["_id"]: row["n"]
            async for row in db[ITEMS_COLLECTION].aggregate(
                [{"$group": {"_id": "$category", "n": {"$sum": 1}}}]
            )
        }
        for category in categories:
            category["item_count"] = counts.get(category["name"], 0)
    return categories


async def create_category(
    db: AsyncIOMotorDatabase, admin: dict[str, Any], name: str
) -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise field_validation_error("name", "Name must not be blank")

    document = {"name": name, "name_lower": name.lower()}
    try:
        result = await db[COLLECTION_NAME].insert_one(document)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This category already exists"
        )

    document["_id"] = result.inserted_id
    category = serialize(document)
    category["item_count"] = 0
    await record_audit(
        db,
        admin,
        action=f"Created category '{name}'",
        target_type=AuditTargetType.CATEGORY,
        target_id=category["id"],
    )
    return category


async def delete_category(
    db: AsyncIOMotorDatabase, admin: dict[str, Any], category_id: str
) -> None:
    category = await db[COLLECTION_NAME].find_one(
        {"_id": to_object_id(category_id, resource="Category")}
    )
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    if await db[ITEMS_COLLECTION].count_documents({"category": category["name"]}, limit=1):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This category is in use by existing reports",
        )

    await db[COLLECTION_NAME].delete_one({"_id": category["_id"]})
    await record_audit(
        db,
        admin,
        action=f"Deleted category '{category['name']}'",
        target_type=AuditTargetType.CATEGORY,
        target_id=str(category["_id"]),
    )

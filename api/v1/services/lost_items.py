from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from api.v1.models.item import ReportType
from api.v1.schemas.lost_item import LostItemCreate
from api.v1.services.items import create_item


async def create_lost_item(
    db: AsyncIOMotorDatabase,
    user_id: str,
    payload: LostItemCreate,
) -> dict[str, Any]:
    data = payload.model_dump(mode="json")
    item = await create_item(
        db,
        user_id,
        ReportType.LOST,
        {
            "item_name": data["item_name"],
            "category": data["category"],
            "color": data["color"],
            "description": data["description"],
            "photo": data["photo"],
            "location": data["last_seen_location"],
            "date": data["date_lost"],
        },
    )
    return {
        **item,
        "last_seen_location": item["location"],
        "date_lost": item["date"],
    }

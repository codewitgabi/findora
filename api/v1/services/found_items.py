from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from api.v1.models.item import ReportType
from api.v1.schemas.found_item import FoundItemCreate
from api.v1.services.items import create_item


async def create_found_item(
    db: AsyncIOMotorDatabase,
    user_id: str,
    payload: FoundItemCreate,
) -> dict[str, Any]:
    data = payload.model_dump(mode="json")
    item = await create_item(
        db,
        user_id,
        ReportType.FOUND,
        {
            "item_name": data["item_name"],
            "category": data["category"],
            "color": data["color"],
            "description": data["description"],
            "photo": data["photo"],
            "location": data["found_location"],
            "date": data["date_found"],
            "condition": data["condition"],
            "handed_to": data["handed_to"],
        },
    )
    return {
        **item,
        "found_location": item["location"],
        "date_found": item["date"],
    }

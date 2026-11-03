from typing import Annotated, Any

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.database import get_db
from api.response import success_response
from api.v1.dependencies.auth import get_current_user
from api.v1.schemas.category import CategoryOut
from api.v1.services.categories import list_categories

router = APIRouter(prefix="/categories", tags=["Categories"])


@router.get("")
async def get_categories(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    """Categories for dropdowns/filters. Admins also receive per-category item counts."""
    is_admin = user["role"] == "admin"
    categories = await list_categories(db, with_counts=is_admin)
    data = {
        "items": [
            CategoryOut(**c).model_dump(mode="json", exclude_none=True) for c in categories
        ],
        "total": len(categories),
    }
    return success_response("Categories retrieved", data=data)

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, UploadFile, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.database import get_db
from api.response import success_response
from api.v1.dependencies.auth import get_current_user
from api.v1.schemas.lost_item import LostItemCreate, LostItemOut
from api.v1.schemas.media import ImageUploadOut
from api.v1.services.images import upload_report_image
from api.v1.services.lost_items import create_lost_item

router = APIRouter(prefix="/lost-items", tags=["Lost Items"])


@router.post("/images", status_code=status.HTTP_201_CREATED)
async def upload_lost_item_image(
    file: Annotated[UploadFile, File(...)],
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    """Upload an image before creating a lost-item report."""
    upload = await upload_report_image(db, user["id"], file, default_name="lost-item")
    data = ImageUploadOut(**upload).model_dump(mode="json")
    return success_response("Image uploaded successfully", status.HTTP_201_CREATED, data)


@router.post("", status_code=status.HTTP_201_CREATED)
async def report_lost_item(
    payload: LostItemCreate,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    """Create a lost-item report using an already-uploaded image URL."""
    item = await create_lost_item(db, user["id"], payload)
    data = LostItemOut(**item).model_dump(mode="json")
    return success_response("Lost item reported successfully", status.HTTP_201_CREATED, data)

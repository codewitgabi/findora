from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, UploadFile, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.database import get_db
from api.response import success_response
from api.v1.dependencies.auth import get_current_user
from api.v1.schemas.found_item import FoundItemCreate, FoundItemOut
from api.v1.schemas.media import ImageUploadOut
from api.v1.services.found_items import create_found_item
from api.v1.services.images import upload_report_image

router = APIRouter(prefix="/found-items", tags=["Found Items"])


@router.post("/images", status_code=status.HTTP_201_CREATED)
async def upload_found_item_image(
    file: Annotated[UploadFile, File(...)],
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    """Upload an image before creating a found-item report."""
    upload = await upload_report_image(db, user["id"], file, default_name="found-item")
    data = ImageUploadOut(**upload).model_dump(mode="json")
    return success_response("Image uploaded successfully", status.HTTP_201_CREATED, data)


@router.post("", status_code=status.HTTP_201_CREATED)
async def report_found_item(
    payload: FoundItemCreate,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    """Create a found-item report using an already-uploaded image URL."""
    item = await create_found_item(db, user["id"], payload)
    data = FoundItemOut(**item).model_dump(mode="json")
    return success_response("Found item reported successfully", status.HTTP_201_CREATED, data)

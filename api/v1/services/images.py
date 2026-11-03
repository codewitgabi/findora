from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from fastapi import UploadFile
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.v1.models.item import IMAGES_COLLECTION_NAME
from api.v1.utils.cloudinary import upload_image
from api.v1.utils.image_hash import compute_image_hash, read_image_upload


async def upload_report_image(
    db: AsyncIOMotorDatabase, user_id: str, file: UploadFile, *, default_name: str
) -> dict[str, Any]:
    """Validate, store and fingerprint an image uploaded ahead of a report.

    The perceptual hash is saved against the returned URL so that creating the
    report later can pick it up without re-downloading the image.
    """
    file_bytes = await read_image_upload(file)
    image_hash = await compute_image_hash(file_bytes)
    upload = await upload_image(file_bytes, filename=file.filename or default_name)

    await db[IMAGES_COLLECTION_NAME].insert_one(
        {
            "url": upload["url"],
            "public_id": upload["public_id"],
            "image_hash": image_hash,
            "user_id": ObjectId(user_id),
            "created_at": datetime.now(timezone.utc),
        }
    )
    return upload


async def get_image_hash(db: AsyncIOMotorDatabase, url: str) -> Optional[str]:
    doc = await db[IMAGES_COLLECTION_NAME].find_one({"url": url}, {"image_hash": 1})
    return doc["image_hash"] if doc else None

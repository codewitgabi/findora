from typing import Any

import cloudinary
import cloudinary.uploader
from fastapi import HTTPException, status
from starlette.concurrency import run_in_threadpool

from api.v1.utils.config import config


def _ensure_configured() -> None:
    if not all(
        (
            config.CLOUDINARY_CLOUD_NAME,
            config.CLOUDINARY_API_KEY,
            config.CLOUDINARY_API_SECRET,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image storage is not configured",
        )


async def upload_image(file_bytes: bytes, *, filename: str) -> dict[str, Any]:
    _ensure_configured()
    cloudinary.config(
        cloud_name=config.CLOUDINARY_CLOUD_NAME,
        api_key=config.CLOUDINARY_API_KEY,
        api_secret=config.CLOUDINARY_API_SECRET,
        secure=True,
    )

    result = await run_in_threadpool(
        cloudinary.uploader.upload,
        file_bytes,
        folder=config.CLOUDINARY_UPLOAD_FOLDER,
        resource_type="image",
        filename_override=filename,
        use_filename=True,
        unique_filename=True,
    )
    return {
        "url": result["secure_url"],
        "public_id": result["public_id"],
        "resource_type": result.get("resource_type", "image"),
    }

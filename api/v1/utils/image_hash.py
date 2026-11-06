import io

from fastapi import HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from api.v1.utils.config import config

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}
HASH_BITS = 64
# Unrelated photos differ in about half the bits, so anything at or beyond this
# distance counts as "no visual similarity".
_MAX_USEFUL_DISTANCE = HASH_BITS // 2


async def read_image_upload(file: UploadFile) -> bytes:
    """Validate type and size of an uploaded image and return its bytes."""
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only JPG and PNG images are supported",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded image is empty",
        )
    if len(file_bytes) > config.MAX_IMAGE_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The uploaded image is too large",
        )
    return file_bytes


def _dhash(file_bytes: bytes) -> str:
    """64-bit difference hash, robust to resizing and mild colour/compression changes."""
    try:
        with Image.open(io.BytesIO(file_bytes)) as image:
            pixels = list(image.convert("L").resize((9, 8), Image.Resampling.LANCZOS).get_flattened_data())
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="The uploaded file is not a valid image",
        ) from exc

    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    return f"{bits:016x}"


async def compute_image_hash(file_bytes: bytes) -> str:
    return await run_in_threadpool(_dhash, file_bytes)


def image_similarity(hash_a: str | None, hash_b: str | None) -> float | None:
    """Visual similarity in [0, 1]; ``None`` when either side has no photo."""
    if not hash_a or not hash_b:
        return None
    distance = (int(hash_a, 16) ^ int(hash_b, 16)).bit_count()
    return max(0.0, 1 - distance / _MAX_USEFUL_DISTANCE)

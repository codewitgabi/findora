from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.v1.models.user import COLLECTION_NAME, AccountStatus, UserRole
from api.v1.schemas.auth import TokenOut
from api.v1.schemas.user import UserRegisterIn
from api.v1.utils.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


async def _create_user(
    db: AsyncIOMotorDatabase,
    *,
    full_name: str,
    email: str,
    phone: Optional[str],
    password_hash: str,
) -> dict[str, Any]:
    document = {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "password_hash": password_hash,
        "role": UserRole.USER.value,
        "account_status": AccountStatus.ACTIVE.value,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db[COLLECTION_NAME].insert_one(document)
    document["_id"] = result.inserted_id
    return _serialize(document)


async def _get_user_by_email(db: AsyncIOMotorDatabase, email: str) -> Optional[dict[str, Any]]:
    doc = await db[COLLECTION_NAME].find_one({"email": email})
    return _serialize(doc) if doc else None


async def get_user_by_id(db: AsyncIOMotorDatabase, user_id: str) -> Optional[dict[str, Any]]:
    if not ObjectId.is_valid(user_id):
        return None
    doc = await db[COLLECTION_NAME].find_one({"_id": ObjectId(user_id)})
    return _serialize(doc) if doc else None


def _issue_tokens(user_id: str) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


async def register_user(db: AsyncIOMotorDatabase, payload: UserRegisterIn) -> dict[str, Any]:
    existing = await _get_user_by_email(db, payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    return await _create_user(
        db,
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_password(payload.password),
    )


async def authenticate_user(db: AsyncIOMotorDatabase, email: str, password: str) -> TokenOut:
    user = await _get_user_by_email(db, email)
    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if user["account_status"] != AccountStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been suspended",
        )

    return _issue_tokens(user["id"])


async def refresh_access_token(db: AsyncIOMotorDatabase, refresh_token: str) -> TokenOut:
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != TokenType.REFRESH.value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user = await get_user_by_id(db, payload["sub"])
    if not user or user["account_status"] != AccountStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    return _issue_tokens(user["id"])

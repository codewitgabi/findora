import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.v1.models.auth import (
    AUTH_ATTEMPTS_COLLECTION,
    PASSWORD_RESETS_COLLECTION,
    AttemptKind,
)
from api.v1.models.user import COLLECTION_NAME, AccountStatus, UserRole
from api.v1.schemas.auth import TokenOut
from api.v1.schemas.user import UserRegisterIn
from api.v1.utils.config import config
from api.v1.utils.errors import field_validation_error
from api.v1.utils.mailer import send_email
from api.v1.utils.mongo import exact_ci
from api.v1.utils.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    token_is_current,
    verify_password,
)


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


def _normalize_email(email: str) -> str:
    return email.strip().lower()


async def _get_user_by_email(db: AsyncIOMotorDatabase, email: str) -> Optional[dict[str, Any]]:
    doc = await db[COLLECTION_NAME].find_one({"email": email})
    if not doc:
        # Accounts created before emails were normalised may be stored in mixed case.
        doc = await db[COLLECTION_NAME].find_one({"email": exact_ci(email)})
    return _serialize(doc) if doc else None


async def get_user_by_id(db: AsyncIOMotorDatabase, user_id: str) -> Optional[dict[str, Any]]:
    if not ObjectId.is_valid(user_id):
        return None
    doc = await db[COLLECTION_NAME].find_one({"_id": ObjectId(user_id)})
    return _serialize(doc) if doc else None


def _issue_tokens(user: dict[str, Any]) -> TokenOut:
    version = user.get("token_version", 0)
    return TokenOut(
        access_token=create_access_token(user["id"], version),
        refresh_token=create_refresh_token(user["id"], version),
    )


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #


async def _recent_attempts(db: AsyncIOMotorDatabase, kind: AttemptKind, email: str) -> int:
    since = datetime.now(timezone.utc) - timedelta(minutes=config.RATE_LIMIT_WINDOW_MINUTES)
    return await db[AUTH_ATTEMPTS_COLLECTION].count_documents(
        {"kind": kind.value, "email": email, "created_at": {"$gte": since}}
    )


async def _record_attempt(db: AsyncIOMotorDatabase, kind: AttemptKind, email: str) -> None:
    await db[AUTH_ATTEMPTS_COLLECTION].insert_one(
        {"kind": kind.value, "email": email, "created_at": datetime.now(timezone.utc)}
    )


def _too_many(what: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many {what}. Try again in {config.RATE_LIMIT_WINDOW_MINUTES} minutes.",
    )


# --------------------------------------------------------------------------- #
# Registration and login
# --------------------------------------------------------------------------- #


async def register_user(db: AsyncIOMotorDatabase, payload: UserRegisterIn) -> dict[str, Any]:
    email = _normalize_email(payload.email)
    allowed = config.allowed_email_domains
    if allowed and email.rsplit("@", 1)[-1] not in allowed:
        raise field_validation_error(
            "email", f"Use your campus email address ({', '.join('@' + d for d in allowed)})"
        )

    if await _get_user_by_email(db, email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    student_id = (payload.student_id or "").strip() or None
    if student_id and await db[COLLECTION_NAME].count_documents({"student_id": student_id}, limit=1):
        raise field_validation_error("student_id", "This student/staff ID is already registered")

    document = {
        "full_name": payload.full_name.strip(),
        "email": email,
        "phone": (payload.phone or "").strip() or None,
        "student_id": student_id,
        "password_hash": hash_password(payload.password),
        "role": UserRole.USER.value,
        "account_status": AccountStatus.ACTIVE.value,
        "token_version": 0,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db[COLLECTION_NAME].insert_one(document)
    document["_id"] = result.inserted_id
    return _serialize(document)


async def authenticate_user(db: AsyncIOMotorDatabase, email: str, password: str) -> TokenOut:
    email = _normalize_email(email)
    if await _recent_attempts(db, AttemptKind.FAILED_LOGIN, email) >= config.LOGIN_MAX_ATTEMPTS:
        raise _too_many("failed sign-in attempts")

    user = await _get_user_by_email(db, email)
    if not user or not verify_password(password, user["password_hash"]):
        await _record_attempt(db, AttemptKind.FAILED_LOGIN, email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if user["account_status"] != AccountStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been suspended",
        )

    await db[AUTH_ATTEMPTS_COLLECTION].delete_many(
        {"kind": AttemptKind.FAILED_LOGIN.value, "email": email}
    )
    return _issue_tokens(user)


async def refresh_access_token(db: AsyncIOMotorDatabase, refresh_token: str) -> TokenOut:
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
    )
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != TokenType.REFRESH.value:
        raise invalid

    user = await get_user_by_id(db, payload["sub"])
    if (
        not user
        or user["account_status"] != AccountStatus.ACTIVE.value
        or not token_is_current(payload, user)
    ):
        raise invalid

    return _issue_tokens(user)


async def revoke_tokens(db: AsyncIOMotorDatabase, user_id: str) -> None:
    """Invalidate every access and refresh token issued to the user."""
    await db[COLLECTION_NAME].update_one(
        {"_id": ObjectId(user_id)}, {"$inc": {"token_version": 1}}
    )


# --------------------------------------------------------------------------- #
# Password reset
# --------------------------------------------------------------------------- #


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def request_password_reset(db: AsyncIOMotorDatabase, email: str) -> None:
    """Email a single-use reset link. Always succeeds so accounts can't be enumerated."""
    email = _normalize_email(email)
    if await _recent_attempts(db, AttemptKind.RESET_REQUEST, email) >= config.PASSWORD_RESET_MAX_REQUESTS:
        raise _too_many("password reset requests")
    await _record_attempt(db, AttemptKind.RESET_REQUEST, email)

    user = await _get_user_by_email(db, email)
    if not user or user["account_status"] != AccountStatus.ACTIVE.value:
        return

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    # Only the newest link works.
    await db[PASSWORD_RESETS_COLLECTION].delete_many({"user_id": ObjectId(user["id"])})
    await db[PASSWORD_RESETS_COLLECTION].insert_one(
        {
            "user_id": ObjectId(user["id"]),
            "token_hash": _hash_reset_token(token),
            "created_at": now,
            "expires_at": now + timedelta(minutes=config.PASSWORD_RESET_EXPIRE_MINUTES),
        }
    )

    link = f"{config.FRONTEND_URL.rstrip('/')}/reset-password?token={token}"
    await send_email(
        user["email"],
        "Reset your Findora password",
        f"Hi {user['full_name']},\n\n"
        f"Use this link to choose a new password. It expires in "
        f"{config.PASSWORD_RESET_EXPIRE_MINUTES} minutes and works once:\n\n{link}\n\n"
        "If you didn't ask for this, you can ignore this email.",
    )


async def reset_password(db: AsyncIOMotorDatabase, token: str, new_password: str) -> None:
    reset = await db[PASSWORD_RESETS_COLLECTION].find_one_and_delete(
        {
            "token_hash": _hash_reset_token(token),
            "expires_at": {"$gt": datetime.now(timezone.utc)},
        }
    )
    if not reset:
        raise field_validation_error("token", "This reset link is invalid or has expired")

    result = await db[COLLECTION_NAME].update_one(
        {"_id": reset["user_id"], "account_status": AccountStatus.ACTIVE.value},
        {"$set": {"password_hash": hash_password(new_password)}, "$inc": {"token_version": 1}},
    )
    if result.matched_count == 0:
        raise field_validation_error("token", "This reset link is invalid or has expired")

    user = await db[COLLECTION_NAME].find_one({"_id": reset["user_id"]}, {"email": 1})
    if user:
        await db[AUTH_ATTEMPTS_COLLECTION].delete_many(
            {"kind": AttemptKind.FAILED_LOGIN.value, "email": _normalize_email(user["email"])}
        )

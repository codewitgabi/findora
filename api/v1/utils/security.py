from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Optional

import jwt
from passlib.context import CryptContext

from api.v1.utils.config import config

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)


def _create_token(
    subject: str, token_type: TokenType, expires_delta: timedelta, version: int
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type.value,
        # Must equal the user's current token_version, so bumping it revokes the token.
        "ver": version,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def create_access_token(user_id: str, version: int = 0) -> str:
    return _create_token(
        user_id,
        TokenType.ACCESS,
        timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES),
        version,
    )


def create_refresh_token(user_id: str, version: int = 0) -> str:
    return _create_token(
        user_id,
        TokenType.REFRESH,
        timedelta(days=config.REFRESH_TOKEN_EXPIRE_DAYS),
        version,
    )


def token_is_current(payload: dict[str, Any], user: dict[str, Any]) -> bool:
    """False once the user logged out everywhere or reset their password."""
    return payload.get("ver", 0) == user.get("token_version", 0)


def decode_token(token: str) -> Optional[dict[str, Any]]:
    """Decode a JWT, returning its payload or None if invalid/expired."""
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None

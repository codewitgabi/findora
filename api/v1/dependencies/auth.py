from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.database import get_db
from api.v1.models.user import STAFF_ROLES, AccountStatus, UserRole
from api.v1.services.auth import get_user_by_id
from api.v1.utils.security import TokenType, decode_token, token_is_current

_bearer_scheme = HTTPBearer(auto_error=True)

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
) -> dict[str, Any]:
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != TokenType.ACCESS.value:
        raise _INVALID_CREDENTIALS

    user = await get_user_by_id(db, payload["sub"])
    if not user or not token_is_current(payload, user):
        raise _INVALID_CREDENTIALS

    if user["account_status"] != AccountStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been suspended",
        )

    return user


async def require_admin(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    if user["role"] != UserRole.ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required",
        )
    return user


async def require_staff(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Admins and lost-property officers."""
    if user["role"] not in STAFF_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff privileges required",
        )
    return user

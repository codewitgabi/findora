from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.database import get_db
from api.response import success_response
from api.v1.dependencies.auth import get_current_user
from api.v1.schemas.auth import RefreshTokenIn, TokenOut, UserLoginIn
from api.v1.schemas.user import UserOut, UserRegisterIn
from api.v1.services.auth import (
    authenticate_user,
    refresh_access_token,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserRegisterIn,
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    user = await register_user(db, payload)
    return success_response(
        "Account created successfully",
        status.HTTP_201_CREATED,
        UserOut(**user).model_dump(mode="json"),
    )


@router.post("/login")
async def login(
    payload: UserLoginIn,
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    tokens = await authenticate_user(db, payload.email, payload.password)
    return success_response("Login successful", data=tokens.model_dump())


@router.post("/refresh")
async def refresh(
    payload: RefreshTokenIn,
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    tokens: TokenOut = await refresh_access_token(db, payload.refresh_token)
    return success_response("Token refreshed", data=tokens.model_dump())


@router.get("/me")
async def me(user: Annotated[dict[str, Any], Depends(get_current_user)]):
    return success_response("User retrieved", data=UserOut(**user).model_dump(mode="json"))

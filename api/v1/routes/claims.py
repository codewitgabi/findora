from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.database import get_db
from api.response import success_response
from api.v1.dependencies.auth import get_current_user
from api.v1.schemas.claim import ClaimDetailOut, ClaimMessageIn, ClaimMessageOut
from api.v1.services.claims import (
    confirm_collection,
    get_claim_detail,
    list_messages,
    post_message,
)

# Routes for a claim's participants: the claimant, the reporter once the claim is
# approved, and admins. Anyone else gets 404.
router = APIRouter(prefix="/claims", tags=["Claims"])

CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]
Database = Annotated[AsyncIOMotorDatabase, Depends(get_db)]


@router.get("/{claim_id}")
async def claim_detail(claim_id: str, user: CurrentUser, db: Database):
    data = ClaimDetailOut(**await get_claim_detail(db, user, claim_id))
    return success_response("Claim retrieved", data=data.model_dump(mode="json"))


@router.post("/{claim_id}/collected")
async def mark_collected(claim_id: str, user: CurrentUser, db: Database):
    await confirm_collection(db, user, claim_id)
    data = ClaimDetailOut(**await get_claim_detail(db, user, claim_id))
    return success_response("Collection confirmed", data=data.model_dump(mode="json"))


@router.get("/{claim_id}/messages")
async def claim_messages(claim_id: str, user: CurrentUser, db: Database):
    rows = await list_messages(db, user, claim_id)
    data = {"items": [ClaimMessageOut(**row).model_dump(mode="json") for row in rows]}
    return success_response("Messages retrieved", data=data)


@router.post("/{claim_id}/messages", status_code=status.HTTP_201_CREATED)
async def send_claim_message(
    claim_id: str, payload: ClaimMessageIn, user: CurrentUser, db: Database
):
    row = await post_message(db, user, claim_id, payload.body)
    return success_response(
        "Message sent",
        status.HTTP_201_CREATED,
        ClaimMessageOut(**row).model_dump(mode="json"),
    )

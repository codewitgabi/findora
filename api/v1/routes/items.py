from datetime import date
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from api.database import get_db
from api.response import success_response
from api.v1.dependencies.auth import get_current_user
from api.v1.dependencies.pagination import PaginationDep
from api.v1.models.item import ItemStatus, ReportType
from api.v1.schemas.claim import ClaimCreate, ClaimCreatedOut
from api.v1.schemas.item import ItemDetailOut, ItemSearchResult
from api.v1.services.claims import create_claim
from api.v1.services.items import (
    SearchFilters,
    get_item_detail,
    search_items,
    search_items_by_image,
)
from api.v1.utils.image_hash import compute_image_hash, read_image_upload
from api.v1.utils.mongo import paginated

router = APIRouter(prefix="/items", tags=["Items"])


def _query_filters(
    q: Optional[str] = None,
    category: Optional[str] = None,
    color: Optional[str] = None,
    location: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    report_type: Optional[ReportType] = None,
    status: Optional[ItemStatus] = None,
) -> SearchFilters:
    return SearchFilters(q, category, color, location, date_from, date_to, report_type, status)


def _form_filters(
    q: Annotated[Optional[str], Form()] = None,
    category: Annotated[Optional[str], Form()] = None,
    color: Annotated[Optional[str], Form()] = None,
    location: Annotated[Optional[str], Form()] = None,
    date_from: Annotated[Optional[date], Form()] = None,
    date_to: Annotated[Optional[date], Form()] = None,
    report_type: Annotated[Optional[ReportType], Form()] = None,
    status: Annotated[Optional[ItemStatus], Form()] = None,
) -> SearchFilters:
    return SearchFilters(q, category, color, location, date_from, date_to, report_type, status)


@router.get("/search")
async def search(
    filters: Annotated[SearchFilters, Depends(_query_filters)],
    pagination: PaginationDep,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    """Text/filter search over approved, unresolved items."""
    rows, total = await search_items(db, filters, pagination)
    data = paginated(
        [ItemSearchResult(**row).model_dump(mode="json") for row in rows], total, pagination
    )
    return success_response("Items retrieved", data=data)


@router.post("/search/image")
async def search_by_image(
    file: Annotated[UploadFile, File(...)],
    filters: Annotated[SearchFilters, Depends(_form_filters)],
    pagination: PaginationDep,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    """Rank approved, unresolved items by similarity to an uploaded photo.

    Results are possible matches only, never a guaranteed identification.
    """
    query_hash = await compute_image_hash(await read_image_upload(file))
    rows, total = await search_items_by_image(db, query_hash, filters, pagination)
    data = paginated(
        [ItemSearchResult(**row).model_dump(mode="json") for row in rows], total, pagination
    )
    return success_response("Possible matches retrieved", data=data)


@router.get("/{item_id}")
async def get_item(
    item_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    item = await get_item_detail(db, item_id, user)
    return success_response(
        "Item retrieved", data=ItemDetailOut(**item).model_dump(mode="json")
    )


@router.post("/{item_id}/claims", status_code=status.HTTP_201_CREATED)
async def submit_claim(
    item_id: str,
    payload: ClaimCreate,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
):
    claim = await create_claim(db, user, item_id, payload.evidence_text)
    return success_response(
        "Claim submitted successfully",
        status.HTTP_201_CREATED,
        ClaimCreatedOut(**claim).model_dump(mode="json"),
    )

from fastapi import APIRouter

from api.v1.routes.admin import router as admin_router
from api.v1.routes.auth import router as auth_router
from api.v1.routes.categories import router as categories_router
from api.v1.routes.found_items import router as found_items_router
from api.v1.routes.items import router as items_router
from api.v1.routes.lost_items import router as lost_items_router
from api.v1.routes.me import router as me_router

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(auth_router)
v1_router.include_router(me_router)
v1_router.include_router(lost_items_router)
v1_router.include_router(found_items_router)
v1_router.include_router(items_router)
v1_router.include_router(categories_router)
v1_router.include_router(admin_router)

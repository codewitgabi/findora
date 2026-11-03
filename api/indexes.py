from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from api.v1.models.audit_log import COLLECTION_NAME as AUDIT_LOGS_COLLECTION
from api.v1.models.category import COLLECTION_NAME as CATEGORIES_COLLECTION
from api.v1.models.claim import COLLECTION_NAME as CLAIMS_COLLECTION
from api.v1.models.item import COLLECTION_NAME as ITEMS_COLLECTION
from api.v1.models.item import IMAGES_COLLECTION_NAME as ITEM_IMAGES_COLLECTION
from api.v1.models.notification import COLLECTION_NAME as NOTIFICATIONS_COLLECTION
from api.v1.models.user import COLLECTION_NAME as USERS_COLLECTION
from api.v1.utils.logger import get_logger

logger = get_logger("indexes")


async def create_indexes(database: AsyncIOMotorDatabase) -> None:
    """
    Ensure all collection indexes exist.
    """

    await database[USERS_COLLECTION].create_index([("email", ASCENDING)], unique=True)

    await database[ITEMS_COLLECTION].create_index(
        [("user_id", ASCENDING), ("created_at", DESCENDING)]
    )
    await database[ITEMS_COLLECTION].create_index(
        [("report_type", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)]
    )
    await database[ITEMS_COLLECTION].create_index(
        [("category", ASCENDING), ("date", DESCENDING)]
    )
    await database[ITEM_IMAGES_COLLECTION].create_index([("url", ASCENDING)], unique=True)

    await database[CATEGORIES_COLLECTION].create_index(
        [("name_lower", ASCENDING)], unique=True
    )

    await database[CLAIMS_COLLECTION].create_index(
        [("user_id", ASCENDING), ("created_at", DESCENDING)]
    )
    await database[CLAIMS_COLLECTION].create_index(
        [("item_id", ASCENDING), ("status", ASCENDING)]
    )
    await database[CLAIMS_COLLECTION].create_index(
        [("status", ASCENDING), ("created_at", DESCENDING)]
    )

    await database[NOTIFICATIONS_COLLECTION].create_index(
        [("user_id", ASCENDING), ("created_at", DESCENDING)]
    )

    await database[AUDIT_LOGS_COLLECTION].create_index(
        [("target_type", ASCENDING), ("created_at", DESCENDING)]
    )

    logger.info("Indexes ensured")

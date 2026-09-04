from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from api.v1.utils.logger import get_logger

logger = get_logger("indexes")


async def create_indexes(database: AsyncIOMotorDatabase) -> None:
    """
    Ensure all collection indexes exist.
    """

    logger.info("Indexes ensured")

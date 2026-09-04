from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from api.v1.utils.config import config
from api.v1.utils.logger import get_logger

logger = get_logger("database")


class MongoDB:
    """
    Lightweight async MongoDB connection manager.

    Wraps a Motor ``AsyncIOMotorClient`` and exposes the target database.
    Call ``connect()`` once at application startup and ``disconnect()`` once
    at shutdown — Motor handles the internal connection pool automatically.

    Attributes:
        _client: The underlying Motor client instance (None until connected).
        _db:     The active database handle (None until connected).
    """

    def __init__(self) -> None:
        self._client: AsyncIOMotorClient | None = None
        self._db: AsyncIOMotorDatabase | None = None

    async def connect(self) -> None:
        """
        Open the Motor connection pool and verify connectivity.

        Reads connection settings from ``config`` and issues a lightweight
        ``ping`` command to confirm the server is reachable before the
        application starts accepting traffic.

        Raises:
            Exception: Propagates any Motor / PyMongo error so the application
                       fails fast at startup rather than silently accepting
                       requests with no database.
        """
        logger.info("Connecting to MongoDB...", extra={"host": config.MONGO_URI})
        try:
            self._client = AsyncIOMotorClient(
                config.MONGO_URI,
                maxPoolSize=config.MONGO_MAX_POOL_SIZE,
                minPoolSize=config.MONGO_MIN_POOL_SIZE,
                serverSelectionTimeoutMS=config.MONGO_SERVER_SELECTION_TIMEOUT_MS,
            )

            # Verify the server is reachable before accepting traffic
            await self._client.admin.command("ping")

            self._db = self._client[config.MONGO_DB_NAME]
            logger.info(
                "MongoDB connected",
                extra={"database": config.MONGO_DB_NAME},
            )
        except Exception as e:
            logger.error(
                "MongoDB connection failed",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise

    async def disconnect(self) -> None:
        """
        Close the Motor connection pool gracefully.

        Safe to call even if ``connect()`` was never successfully completed —
        the method is a no-op when no client exists.
        """
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None
            logger.info("MongoDB disconnected")

    def get_db(self) -> AsyncIOMotorDatabase:
        """
        Return the active database handle.

        Raises:
            RuntimeError: If called before ``connect()`` has been awaited,
                          i.e. the application wired up routes without
                          initialising the database first.
        """
        if self._db is None:
            raise RuntimeError(
                "Database is not initialised. Did you call await db.connect()?"
            )

        return self._db


# Module-level singleton — import this everywhere you need the database.
db = MongoDB()


async def get_db() -> AsyncIOMotorDatabase:
    """FastAPI dependency that returns the active Motor database handle."""
    return db.get_db()

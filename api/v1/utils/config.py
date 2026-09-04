from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

load_dotenv()


class Config(BaseSettings):
    PORT: int = 5001

    MONGO_URI: Optional[str] = None
    MONGO_DB_NAME: Optional[str] = None
    MONGO_MAX_POOL_SIZE: int = 10  # max concurrent connections per pool
    MONGO_MIN_POOL_SIZE: int = 1  # connections kept alive when idle
    MONGO_SERVER_SELECTION_TIMEOUT_MS: int = 5000  # fail fast on bad URI / host

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=True, env_file_encoding="utf-8"
    )


config = Config()

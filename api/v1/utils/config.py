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

    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None
    CLOUDINARY_UPLOAD_FOLDER: str = "findora"
    MAX_IMAGE_UPLOAD_BYTES: int = 10 * 1024 * 1024

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=True, env_file_encoding="utf-8"
    )


config = Config()

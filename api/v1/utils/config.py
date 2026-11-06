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

    # Comma-separated email domains allowed to register (e.g. "unilag.edu.ng").
    # Empty allows any domain.
    ALLOWED_EMAIL_DOMAINS: str = ""

    # Public URL of the web app, used in password-reset links.
    FRONTEND_URL: str = "http://localhost:5173"
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30

    # Outgoing email. When SMTP_HOST is empty, emails are written to the log instead.
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: str = "Findora <no-reply@findora.local>"
    SMTP_USE_TLS: bool = True

    # Failed logins (and reset requests) allowed per email inside the window.
    LOGIN_MAX_ATTEMPTS: int = 5
    PASSWORD_RESET_MAX_REQUESTS: int = 3
    RATE_LIMIT_WINDOW_MINUTES: int = 15

    # Closed, resolved and rejected reports (with their claims and messages) and read
    # notifications older than this are deleted. 0 disables the purge.
    RETENTION_DAYS: int = 365

    @property
    def allowed_email_domains(self) -> list[str]:
        return [d.strip().lower().lstrip("@") for d in self.ALLOWED_EMAIL_DOMAINS.split(",") if d.strip()]

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=True, env_file_encoding="utf-8"
    )


config = Config()

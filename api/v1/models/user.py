from datetime import datetime
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, EmailStr

COLLECTION_NAME = "Users"


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class User(BaseModel):
    """Full shape of a document in the Users collection."""

    id: str
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    password_hash: str
    role: UserRole
    account_status: AccountStatus
    created_at: datetime

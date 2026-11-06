from datetime import datetime
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, EmailStr

COLLECTION_NAME = "Users"


class UserRole(StrEnum):
    USER = "user"
    # Campus security / lost-property officer: reviews reports and claims, records
    # handovers. Cannot manage users, categories or read the audit log.
    OFFICER = "officer"
    ADMIN = "admin"


STAFF_ROLES = (UserRole.ADMIN.value, UserRole.OFFICER.value)


class AccountStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class User(BaseModel):
    """Full shape of a document in the Users collection."""

    id: str
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    student_id: Optional[str] = None
    password_hash: str
    # Bumped on logout / password reset to revoke every issued token.
    token_version: int = 0
    role: UserRole
    account_status: AccountStatus
    created_at: datetime

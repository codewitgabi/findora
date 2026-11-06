from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from api.v1.models.user import AccountStatus, UserRole


class UserOut(BaseModel):
    id: str
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    student_id: Optional[str] = None
    role: UserRole
    account_status: AccountStatus
    created_at: datetime


class UserRegisterIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: Optional[str] = Field(default=None, max_length=30)
    # Campus student or staff number. Optional, but unique when given.
    student_id: Optional[str] = Field(default=None, max_length=40)
    password: str = Field(min_length=8, max_length=128)


class UserUpdateIn(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=30)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)

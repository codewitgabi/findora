from pydantic import BaseModel, EmailStr


class UserLoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshTokenIn(BaseModel):
    refresh_token: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

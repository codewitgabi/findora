"""Shared fixtures for the API test suite.

Tests run the real FastAPI app in-process (httpx + ASGITransport) against a throwaway
MongoDB database that is created for each test and dropped afterwards. Point
``TEST_MONGO_URI`` at a server to use (default: mongodb://localhost:27017/). Tests
are skipped when no server is reachable.
"""

import io
import os
import random
import uuid
from typing import Any

import httpx
import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from PIL import Image, ImageDraw
from pymongo.errors import PyMongoError

from api.database import get_db
from api.indexes import create_indexes
from api.v1.services import images as images_service
from api.v1.services.categories import seed_categories
from api.v1.utils.config import config
from main import app

MONGO_URI = os.getenv("TEST_MONGO_URI", "mongodb://localhost:27017/")


@pytest_asyncio.fixture
async def db():
    client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=2000)
    try:
        await client.admin.command("ping")
    except PyMongoError:
        pytest.skip(f"MongoDB not reachable at {MONGO_URI}")
    name = f"findora_test_{uuid.uuid4().hex[:10]}"
    database = client[name]
    await create_indexes(database)
    await seed_categories(database)
    try:
        yield database
    finally:
        await client.drop_database(name)
        client.close()


@pytest.fixture(autouse=True)
def test_config(monkeypatch):
    """Predictable settings regardless of the developer's .env."""
    monkeypatch.setattr(config, "ALLOWED_EMAIL_DOMAINS", "")
    monkeypatch.setattr(config, "SMTP_HOST", None)
    monkeypatch.setattr(config, "LOGIN_MAX_ATTEMPTS", 5)
    monkeypatch.setattr(config, "PASSWORD_RESET_MAX_REQUESTS", 3)


@pytest.fixture(autouse=True)
def fake_cloudinary(monkeypatch):
    """Uploads skip Cloudinary but still go through validation and fingerprinting."""

    async def upload_image(file_bytes: bytes, *, filename: str) -> dict[str, Any]:
        public_id = f"test/{uuid.uuid4().hex}"
        return {
            "url": f"https://res.cloudinary.com/test/image/upload/{public_id}.png",
            "public_id": public_id,
            "resource_type": "image",
        }

    monkeypatch.setattr(images_service, "upload_image", upload_image)


@pytest.fixture
def sent_emails(monkeypatch):
    """Capture outgoing email instead of sending it."""
    outbox: list[dict[str, str]] = []

    async def send_email(to: str, subject: str, body: str) -> bool:
        outbox.append({"to": to, "subject": subject, "body": body})
        return True

    from api.v1.services import auth as auth_service

    monkeypatch.setattr(auth_service, "send_email", send_email)
    return outbox


@pytest_asyncio.fixture
async def client(db):
    app.dependency_overrides[get_db] = lambda: db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1") as http:
        yield http
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class Api:
    """Thin wrapper that unwraps the success envelope and keeps the auth header."""

    def __init__(self, http: httpx.AsyncClient, tokens: dict[str, str], user: dict[str, Any]):
        self.http = http
        self.tokens = tokens
        self.user = user

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens['access_token']}"}

    async def request(self, method: str, path: str, expect: int = 200, **kwargs) -> Any:
        response = await self.http.request(method, path, headers=self.headers, **kwargs)
        assert response.status_code == expect, (
            f"{method} {path} -> {response.status_code} (wanted {expect}): {response.text}"
        )
        return response.json().get("data")

    async def get(self, path: str, expect: int = 200, **kw):
        return await self.request("GET", path, expect, **kw)

    async def post(self, path: str, expect: int = 200, **kw):
        return await self.request("POST", path, expect, **kw)

    async def patch(self, path: str, expect: int = 200, **kw):
        return await self.request("PATCH", path, expect, **kw)

    async def delete(self, path: str, expect: int = 200, **kw):
        return await self.request("DELETE", path, expect, **kw)


async def make_user(client, db, name: str, *, role: str = "user", password: str = "password123") -> Api:
    email = f"{name.lower()}@campus.edu"
    response = await client.post(
        "/auth/register", json={"full_name": name, "email": email, "password": password}
    )
    assert response.status_code == 201, response.text
    user = response.json()["data"]
    if role != "user":
        await db["Users"].update_one({"email": email}, {"$set": {"role": role}})
    login = await client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return Api(client, login.json()["data"], {**user, "role": role, "password": password})


@pytest_asyncio.fixture
async def users(client, db):
    """alice (lost something), bob (finder), carol, eve (other users), admin, officer."""
    return {
        name.lower(): await make_user(client, db, name, role=role)
        for name, role in (
            ("Alice", "user"),
            ("Bob", "user"),
            ("Carol", "user"),
            ("Eve", "user"),
            ("Admin", "admin"),
            ("Officer", "officer"),
        )
    }


def make_image(seed: int, size: int = 256) -> Image.Image:
    """A deterministic, visually distinctive test picture."""
    rng = random.Random(seed)
    image = Image.new("RGB", (size, size), tuple(rng.randrange(256) for _ in range(3)))
    draw = ImageDraw.Draw(image)
    for _ in range(8):
        x0, y0 = rng.randrange(size), rng.randrange(size)
        x1, y1 = rng.randrange(x0, size + 1), rng.randrange(y0, size + 1)
        colour = tuple(rng.randrange(256) for _ in range(3))
        if rng.random() < 0.5:
            draw.rectangle((x0, y0, x1, y1), fill=colour)
        else:
            draw.ellipse((x0, y0, x1, y1), fill=colour)
    return image


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def upload_photo(api: Api, kind: str, seed: int) -> str:
    data = await api.post(
        f"/{kind}-items/images",
        expect=201,
        files={"file": (f"item-{seed}.png", png_bytes(make_image(seed)), "image/png")},
    )
    return data["url"]


def lost_payload(**overrides) -> dict[str, Any]:
    return {
        "item_name": "Black backpack",
        "category": "Bags",
        "color": "Black",
        "description": "Laptop backpack with a blue keychain",
        "last_seen_location": "Main Library",
        "date_lost": "2026-10-04",
        **overrides,
    }


def found_payload(photo: str, **overrides) -> dict[str, Any]:
    return {
        "item_name": "Black backpack",
        "category": "Bags",
        "color": "Black",
        "description": "Found a backpack on a chair",
        "photo": photo,
        "found_location": "Main Library",
        "date_found": "2026-10-05",
        "condition": "Good",
        "handed_to": "Security office",
        **overrides,
    }


async def approve(admin: Api, item_id: str) -> None:
    await admin.patch(f"/admin/reports/{item_id}/status", json={"status": "active"})


async def notifications(api: Api) -> list[dict[str, Any]]:
    return (await api.get("/me/notifications", params={"page_size": 100}))["items"]

import re

from api.v1.utils.config import config

from .conftest import make_user


async def register(client, **body):
    payload = {"full_name": "Test User", "email": "test@campus.edu", "password": "password123", **body}
    return await client.post("/auth/register", json=payload)


async def test_register_login_me_round_trip(client, db):
    response = await register(client, email="  Mixed.Case@Campus.EDU ", student_id="CSC/2021/001")
    assert response.status_code == 201, response.text
    user = response.json()["data"]
    assert user["email"] == "mixed.case@campus.edu"
    assert user["student_id"] == "CSC/2021/001"
    assert "password_hash" not in user

    login = await client.post("/auth/login", json={"email": "MIXED.case@campus.edu", "password": "password123"})
    assert login.status_code == 200
    token = login.json()["data"]["access_token"]
    me = await client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["data"]["student_id"] == "CSC/2021/001"


async def test_campus_email_domains_are_enforced(client, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_EMAIL_DOMAINS", "campus.edu, staff.campus.edu")
    rejected = await register(client, email="someone@gmail.com")
    assert rejected.status_code == 422
    assert rejected.json()["errors"][0]["field"] == "email"
    assert (await register(client, email="a@campus.edu")).status_code == 201
    assert (await register(client, email="b@staff.campus.edu")).status_code == 201


async def test_duplicate_email_and_student_id_are_rejected(client):
    assert (await register(client, student_id="ID-1")).status_code == 201
    assert (await register(client, email="TEST@campus.edu")).status_code == 409
    dup = await register(client, email="other@campus.edu", student_id="ID-1")
    assert dup.status_code == 422
    assert dup.json()["errors"][0]["field"] == "student_id"
    # Several accounts without a student id are fine (partial unique index).
    assert (await register(client, email="x@campus.edu")).status_code == 201
    assert (await register(client, email="y@campus.edu")).status_code == 201


async def test_login_is_rate_limited_and_success_resets_the_counter(client):
    await register(client)
    bad = {"email": "test@campus.edu", "password": "wrong-password"}
    for _ in range(4):
        assert (await client.post("/auth/login", json=bad)).status_code == 401
    good = {"email": "test@campus.edu", "password": "password123"}
    assert (await client.post("/auth/login", json=good)).status_code == 200
    for _ in range(5):
        assert (await client.post("/auth/login", json=bad)).status_code == 401
    locked = await client.post("/auth/login", json=good)
    assert locked.status_code == 429
    assert "Too many" in locked.json()["message"]


async def test_logout_revokes_access_and_refresh_tokens(client, db):
    alice = await make_user(client, db, "Alice")
    tokens = dict(alice.tokens)
    await alice.post("/auth/logout")
    assert (await client.get("/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})).status_code == 401
    assert (await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})).status_code == 401
    # Logging in again issues working tokens.
    again = await client.post("/auth/login", json={"email": "alice@campus.edu", "password": "password123"})
    assert again.status_code == 200
    fresh = again.json()["data"]
    assert (await client.post("/auth/refresh", json={"refresh_token": fresh["refresh_token"]})).status_code == 200


async def test_password_reset_flow(client, db, sent_emails):
    alice = await make_user(client, db, "Alice")
    old_refresh = alice.tokens["refresh_token"]

    response = await client.post("/auth/forgot-password", json={"email": "ALICE@campus.edu"})
    assert response.status_code == 200
    assert len(sent_emails) == 1 and sent_emails[0]["to"] == "alice@campus.edu"
    token = re.search(r"reset-password\?token=([\w-]+)", sent_emails[0]["body"]).group(1)

    # Unknown emails get the same answer and no email (no account enumeration).
    unknown = await client.post("/auth/forgot-password", json={"email": "nobody@campus.edu"})
    assert unknown.status_code == 200 and unknown.json()["message"] == response.json()["message"]
    assert len(sent_emails) == 1

    weak = await client.post("/auth/reset-password", json={"token": token, "new_password": "short"})
    assert weak.status_code == 422

    done = await client.post("/auth/reset-password", json={"token": token, "new_password": "brand-new-pass"})
    assert done.status_code == 200, done.text

    # Single use, old password and old sessions are gone, new password works.
    reused = await client.post("/auth/reset-password", json={"token": token, "new_password": "another-pass1"})
    assert reused.status_code == 422 and reused.json()["errors"][0]["field"] == "token"
    assert (await client.post("/auth/refresh", json={"refresh_token": old_refresh})).status_code == 401
    assert (await client.post("/auth/login", json={"email": "alice@campus.edu", "password": "password123"})).status_code == 401
    assert (await client.post("/auth/login", json={"email": "alice@campus.edu", "password": "brand-new-pass"})).status_code == 200


async def test_only_the_newest_reset_link_works_and_requests_are_rate_limited(client, db, sent_emails):
    await make_user(client, db, "Alice")
    for _ in range(2):
        assert (await client.post("/auth/forgot-password", json={"email": "alice@campus.edu"})).status_code == 200
    first, second = (re.search(r"token=([\w-]+)", m["body"]).group(1) for m in sent_emails)
    stale = await client.post("/auth/reset-password", json={"token": first, "new_password": "brand-new-pass"})
    assert stale.status_code == 422
    assert (await client.post("/auth/reset-password", json={"token": second, "new_password": "brand-new-pass"})).status_code == 200

    assert (await client.post("/auth/forgot-password", json={"email": "alice@campus.edu"})).status_code == 200
    assert (await client.post("/auth/forgot-password", json={"email": "alice@campus.edu"})).status_code == 429


async def test_suspended_users_are_locked_out(client, db, users):
    eve = users["eve"]
    await users["admin"].patch(f"/admin/users/{eve.user['id']}", json={"account_status": "suspended"})
    assert (await client.get("/me", headers=eve.headers)).status_code == 403
    login = await client.post("/auth/login", json={"email": "eve@campus.edu", "password": "password123"})
    assert login.status_code == 403

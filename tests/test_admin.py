from .conftest import approve, found_payload, lost_payload, make_user, notifications, upload_photo


async def test_officer_handles_reports_and_claims_but_not_admin_areas(users):
    alice, eve, officer = users["alice"], users["eve"], users["officer"]
    lost = await alice.post("/lost-items", expect=201, json=lost_payload())
    await officer.get("/admin/stats")
    assert (await officer.get("/admin/reports", params={"status": "pending"}))["total"] == 1
    await officer.patch(f"/admin/reports/{lost['id']}/status", json={"status": "active"})

    claim = await eve.post(f"/items/{lost['id']}/claims", expect=201, json={"evidence_text": "I found it at the gym"})
    await officer.get("/admin/claims")
    await officer.patch(f"/admin/claims/{claim['id']}", json={"status": "approved", "pickup_location": "Security office"})
    assert (await officer.get(f"/claims/{claim['id']}"))["my_role"] == "admin"
    await officer.post(f"/claims/{claim['id']}/collected")

    await officer.get("/admin/users", expect=403)
    await officer.get("/admin/audit-logs", expect=403)
    await officer.post("/admin/categories", expect=403, json={"name": "Sports"})
    await officer.patch(f"/admin/users/{eve.user['id']}", expect=403, json={"account_status": "suspended"})
    await eve.get("/admin/reports", expect=403)


async def test_admin_assigns_and_removes_the_officer_role(client, db, users):
    admin = users["admin"]
    dave = await make_user(client, db, "Dave")
    await dave.get("/admin/reports", expect=403)

    row = await admin.patch(f"/admin/users/{dave.user['id']}", json={"role": "officer"})
    assert row["role"] == "officer"
    # The role change revokes old tokens so the UI picks up the new role on sign-in.
    await dave.get("/me", expect=401)
    login = await client.post("/auth/login", json={"email": "dave@campus.edu", "password": "password123"})
    dave.tokens = login.json()["data"]
    await dave.get("/admin/reports")

    await admin.patch(f"/admin/users/{dave.user['id']}", expect=403, json={"role": "admin"})
    await admin.patch(f"/admin/users/{admin.user['id']}", expect=403, json={"role": "user"})
    await admin.patch(f"/admin/users/{dave.user['id']}", expect=422, json={})
    assert (await admin.patch(f"/admin/users/{dave.user['id']}", json={"role": "user"}))["role"] == "user"
    actions = [entry["action"] for entry in (await admin.get("/admin/audit-logs"))["items"]]
    assert "Made Dave a lost-property officer" in actions and "Removed officer role from Dave" in actions


async def test_admin_removes_inappropriate_and_duplicate_reports(users):
    alice, bob, eve, admin = users["alice"], users["bob"], users["eve"], users["admin"]
    spam = await eve.post("/lost-items", expect=201, json=lost_payload(item_name="Buy cheap phones", description="spam"))
    await admin.patch(
        f"/admin/reports/{spam['id']}/status",
        json={"status": "closed", "note": "Not a lost item"},
    )
    detail = await eve.get(f"/items/{spam['id']}")
    assert detail["status"] == "closed" and detail["close_reason"] == "removed_by_admin"
    assert any("removed by an administrator" in n["message"] for n in await notifications(eve))

    photo = await upload_photo(bob, "found", seed=21)
    first = await bob.post("/found-items", expect=201, json=found_payload(photo))
    second = await bob.post("/found-items", expect=201, json=found_payload(photo))
    await approve(admin, first["id"])
    await approve(admin, second["id"])
    claim = await alice.post(f"/items/{second['id']}/claims", expect=201, json={"evidence_text": "My backpack, blue keychain"})

    await admin.patch(f"/admin/reports/{second['id']}/status", expect=422, json={"status": "closed", "duplicate_of": second["id"]})
    await admin.patch(f"/admin/reports/{second['id']}/status", expect=422, json={"status": "closed", "duplicate_of": "65f1a2b3c4d5e6f789012345"})
    await admin.patch(f"/admin/reports/{second['id']}/status", expect=422, json={"status": "resolved", "duplicate_of": first["id"]})
    row = await admin.patch(
        f"/admin/reports/{second['id']}/status",
        json={"status": "closed", "duplicate_of": first["id"]},
    )
    assert row["status"] == "closed"
    assert (await bob.get(f"/items/{second['id']}"))["close_reason"] == "duplicate"
    dup_note = next(n for n in await notifications(bob) if "duplicate" in n["message"])
    assert dup_note["item_id"] == first["id"]
    assert (await alice.get("/me/claims"))["items"][0]["id"] == claim["id"]
    assert (await alice.get("/me/claims"))["items"][0]["status"] == "rejected"

    # Finished reports can't be removed again.
    await admin.patch(f"/admin/reports/{second['id']}/status", expect=409, json={"status": "closed"})
    logs = (await admin.get("/admin/audit-logs"))["items"]
    assert any("as a duplicate of" in entry["action"] for entry in logs)
    assert any(entry["details"] == "Not a lost item" for entry in logs)

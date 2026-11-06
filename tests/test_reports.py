from .conftest import approve, found_payload, lost_payload, notifications, upload_photo


async def test_lost_report_photo_is_optional_but_found_report_needs_one(users):
    alice, bob = users["alice"], users["bob"]
    lost = await alice.post("/lost-items", expect=201, json=lost_payload())
    assert lost["photo"] is None and lost["status"] == "pending"

    no_photo = found_payload(photo="x")
    no_photo.pop("photo")
    await bob.post("/found-items", expect=422, json=no_photo)

    detail = await alice.get(f"/items/{lost['id']}")
    assert detail["photo"] is None


async def test_identifying_marks_are_only_visible_to_owner_and_staff(users):
    alice, eve, admin, officer = users["alice"], users["eve"], users["admin"], users["officer"]
    lost = await alice.post("/lost-items", expect=201, json=lost_payload(identifying_marks="Name tag 'A.O.' inside"))
    await approve(admin, lost["id"])

    assert (await alice.get(f"/items/{lost['id']}"))["identifying_marks"] == "Name tag 'A.O.' inside"
    assert (await admin.get(f"/items/{lost['id']}"))["identifying_marks"] == "Name tag 'A.O.' inside"
    assert (await officer.get(f"/items/{lost['id']}"))["identifying_marks"] == "Name tag 'A.O.' inside"
    assert (await eve.get(f"/items/{lost['id']}"))["identifying_marks"] is None
    results = await eve.get("/items/search", params={"q": "A.O."})
    assert results["total"] == 0  # private marks are not searchable either


async def test_owner_sees_possible_matches_while_report_awaits_review(users):
    alice, bob, eve, admin = users["alice"], users["bob"], users["eve"], users["admin"]
    photo = await upload_photo(bob, "found", seed=1)
    found = await bob.post("/found-items", expect=201, json=found_payload(photo))
    await approve(admin, found["id"])

    lost = await alice.post("/lost-items", expect=201, json=lost_payload())
    detail = await alice.get(f"/items/{lost['id']}")
    assert detail["status"] == "pending"
    assert [s["id"] for s in detail["similar_items"]] == [found["id"]]

    # Pending reports stay invisible to everyone else.
    await eve.get(f"/items/{lost['id']}", expect=404)


async def test_owner_can_edit_their_report(users):
    alice, eve, admin = users["alice"], users["eve"], users["admin"]
    lost = await alice.post("/lost-items", expect=201, json=lost_payload())
    before = await alice.get(f"/items/{lost['id']}")

    await eve.patch(f"/items/{lost['id']}", expect=404, json={"color": "Blue"})
    await alice.patch(f"/items/{lost['id']}", expect=422, json={"handed_to": "Security office"})
    await alice.patch(f"/items/{lost['id']}", expect=422, json={"category": "Spaceships"})
    await alice.patch(f"/items/{lost['id']}", expect=422, json={"item_name": None})

    edited = await alice.patch(f"/items/{lost['id']}", json={"color": "Navy", "identifying_marks": "Torn strap"})
    assert edited["color"] == "Navy" and edited["identifying_marks"] == "Torn strap"
    assert edited["status"] == "pending"
    assert edited["updated_at"] > before["updated_at"]

    photo = await upload_photo(alice, "lost", seed=7)
    with_photo = await alice.patch(f"/items/{lost['id']}", json={"photo": photo})
    assert with_photo["photo"] == photo
    removed = await alice.patch(f"/items/{lost['id']}", json={"photo": None})
    assert removed["photo"] is None

    await approve(admin, lost["id"])
    assert (await alice.get(f"/items/{lost['id']}"))["status"] == "active"


async def test_material_edit_sends_approved_report_back_for_review(users, db):
    alice, bob, admin = users["alice"], users["bob"], users["admin"]
    photo = await upload_photo(bob, "found", seed=2)
    found = await bob.post("/found-items", expect=201, json=found_payload(photo))
    lost = await alice.post("/lost-items", expect=201, json=lost_payload(photo=photo))
    await approve(admin, found["id"])
    await approve(admin, lost["id"])
    assert (await bob.get(f"/items/{found['id']}"))["status"] == "matched"

    # Handover location is a review-free edit.
    moved = await bob.patch(f"/items/{found['id']}", json={"handed_to": "Library front desk"})
    assert moved["status"] == "matched" and moved["handed_to"] == "Library front desk"

    # Changing what the item is goes back to review and drops the match on both sides.
    renamed = await bob.patch(f"/items/{found['id']}", json={"item_name": "Grey backpack"})
    assert renamed["status"] == "pending"
    assert (await alice.get(f"/items/{lost['id']}"))["status"] == "active"
    assert (await db["Items"].find_one({"item_name": "Black backpack", "report_type": "lost"}))["matched_with"] == []


async def test_edit_is_blocked_while_claims_are_under_review(users):
    bob, eve, admin = users["bob"], users["eve"], users["admin"]
    photo = await upload_photo(bob, "found", seed=3)
    found = await bob.post("/found-items", expect=201, json=found_payload(photo))
    await approve(admin, found["id"])
    await eve.post(f"/items/{found['id']}/claims", expect=201, json={"evidence_text": "It has my initials inside"})
    await bob.patch(f"/items/{found['id']}", expect=409, json={"description": "Changed"})


async def test_owner_close_rejects_claims_releases_matches_and_hides_report(users):
    alice, bob, eve, admin = users["alice"], users["bob"], users["eve"], users["admin"]
    photo = await upload_photo(alice, "lost", seed=4)
    lost = await alice.post("/lost-items", expect=201, json=lost_payload(photo=photo))
    found = await bob.post("/found-items", expect=201, json=found_payload(photo))
    await approve(admin, lost["id"])
    await approve(admin, found["id"])
    claim = await eve.post(f"/items/{lost['id']}/claims", expect=201, json={"evidence_text": "I found this one at the gym"})

    await eve.post(f"/items/{lost['id']}/close", expect=404, json={"reason": "found_it"})
    await alice.post(f"/items/{lost['id']}/close", expect=422, json={"reason": "removed_by_admin"})
    closed = await alice.post(f"/items/{lost['id']}/close", json={"reason": "found_it", "note": "It was in my car"})
    assert closed["status"] == "closed" and closed["close_reason"] == "found_it"

    claims = (await eve.get("/me/claims"))["items"]
    assert claims[0]["id"] == claim["id"] and claims[0]["status"] == "rejected"
    assert "found the item themselves" in claims[0]["admin_note"]
    assert any(n["title"] == "Claim closed" for n in await notifications(eve))

    assert (await bob.get(f"/items/{found['id']}"))["status"] == "active"
    assert any(n["title"] == "Possible match no longer available" for n in await notifications(bob))

    assert (await eve.get("/items/search", params={"q": "backpack"}))["total"] == 1  # only bob's
    await alice.patch(f"/items/{lost['id']}", expect=409, json={"color": "Red"})
    await alice.post(f"/items/{lost['id']}/close", expect=409, json={"reason": "other"})


async def test_admin_resolving_a_report_closes_its_pending_claims(users):
    """Regression: claims used to stay 'pending' forever on a report an admin resolved."""
    bob, eve, carol, admin = users["bob"], users["eve"], users["carol"], users["admin"]
    photo = await upload_photo(bob, "found", seed=5)
    found = await bob.post("/found-items", expect=201, json=found_payload(photo))
    await approve(admin, found["id"])
    for user in (eve, carol):
        await user.post(f"/items/{found['id']}/claims", expect=201, json={"evidence_text": "This is mine, really"})

    await admin.patch(f"/admin/reports/{found['id']}/status", json={"status": "resolved", "note": "Owner collected in person"})
    for user in (eve, carol):
        claim = (await user.get("/me/claims"))["items"][0]
        assert claim["status"] == "rejected"
        assert "administrator resolved" in claim["admin_note"]
    assert (await admin.get("/admin/stats"))["pending_claims"] == 0

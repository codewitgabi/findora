from .conftest import approve, found_payload, lost_payload, notifications, upload_photo


async def setup_match(users):
    """alice lost a backpack, carol lost a similar one, bob found it (still has it)."""
    alice, bob, carol, admin = users["alice"], users["bob"], users["carol"], users["admin"]
    photo = await upload_photo(bob, "found", seed=11)
    lost_a = await alice.post("/lost-items", expect=201, json=lost_payload(photo=photo))
    lost_c = await carol.post("/lost-items", expect=201, json=lost_payload(photo=photo))
    found = await bob.post("/found-items", expect=201, json=found_payload(photo, handed_to="I still have it"))
    for item in (lost_a, lost_c, found):
        await approve(admin, item["id"])
    return lost_a, lost_c, found


async def test_full_claim_handover_flow(users):
    alice, bob, carol, eve, admin = (users[k] for k in ("alice", "bob", "carol", "eve", "admin"))
    lost_a, lost_c, found = await setup_match(users)

    # Match notifications link to the other report, and the owner sees it listed.
    match = next(n for n in await notifications(alice) if n["type"] == "match")
    assert match["item_id"] == found["id"]
    assert [m["id"] for m in (await alice.get(f"/items/{lost_a['id']}"))["matched_items"]] == [found["id"]]
    assert (await eve.get(f"/items/{found['id']}"))["matched_items"] == []
    assert (await eve.get(f"/items/{found['id']}"))["handed_to"] == "I still have it"

    claim = await alice.post(f"/items/{found['id']}/claims", expect=201, json={"evidence_text": "Blue keychain, dented zip"})
    rival = await eve.post(f"/items/{found['id']}/claims", expect=201, json={"evidence_text": "Mine, notes are inside"})
    assert any(n["title"] == "New claim on your report" for n in await notifications(bob))
    await bob.get(f"/claims/{claim['id']}", expect=404)  # reporter waits for approval
    await carol.get(f"/claims/{claim['id']}", expect=404)

    # Admin asks a question; claimant answers; the queue flags the reply.
    await admin.post(f"/claims/{claim['id']}/messages", expect=201, json={"body": "What laptop is inside?"})
    assert any(n["type"] == "message" and n["claim_id"] == claim["id"] for n in await notifications(alice))
    await alice.post(f"/claims/{claim['id']}/messages", expect=201, json={"body": "A grey ThinkPad"})
    queue = (await admin.get("/admin/claims", params={"status": "pending"}))["items"]
    assert next(c for c in queue if c["id"] == claim["id"])["has_unread_messages"] is True
    thread = (await admin.get(f"/claims/{claim['id']}/messages"))["items"]
    assert [m["sender_role"] for m in thread] == ["admin", "claimant"]
    queue = (await admin.get("/admin/claims", params={"status": "pending"}))["items"]
    assert next(c for c in queue if c["id"] == claim["id"])["has_unread_messages"] is False
    await bob.post(f"/claims/{claim['id']}/messages", expect=404, json={"body": "hi"})

    # Approval needs a pickup location.
    missing = await admin.http.patch(f"/admin/claims/{claim['id']}", headers=admin.headers, json={"status": "approved"})
    assert missing.status_code == 422 and missing.json()["errors"][0]["field"] == "pickup_location"
    await admin.patch(
        f"/admin/claims/{claim['id']}",
        json={"status": "approved", "pickup_location": "Security office, Block B", "admin_note": "Bring your ID."},
    )

    assert (await bob.get(f"/items/{found['id']}"))["status"] == "claimed"
    assert (await alice.get(f"/items/{lost_a['id']}"))["status"] == "claimed"
    carol_report = await carol.get(f"/items/{lost_c['id']}")
    assert carol_report["status"] == "active" and carol_report["matched_items"] == []
    assert any(n["title"] == "Possible match no longer available" for n in await notifications(carol))
    assert (await eve.get("/me/claims"))["items"][0]["id"] == rival["id"]
    assert (await eve.get("/me/claims"))["items"][0]["status"] == "rejected"
    approved_note = next(n for n in await notifications(alice) if n["title"].startswith("Claim approved"))
    assert "Security office, Block B" in approved_note["message"] and "Bring your ID." in approved_note["message"]
    assert any("arrange the handover" in n["message"] for n in await notifications(bob))
    assert found["id"] not in [r["id"] for r in (await eve.get("/items/search"))["items"]]
    await carol.post(f"/items/{found['id']}/claims", expect=404, json={"evidence_text": "Mine mine mine mine"})

    # The finder joins the thread without seeing the evidence.
    bob_view = await bob.get(f"/claims/{claim['id']}")
    assert bob_view["my_role"] == "reporter" and bob_view["evidence_text"] is None and bob_view["can_message"]
    await bob.post(f"/claims/{claim['id']}/messages", expect=201, json={"body": "Library desk, 2-4pm"})
    assert (await bob.get(f"/items/{found['id']}"))["handover"]["handover_status"] == "awaiting_pickup"
    my_claim = (await alice.get("/me/claims"))["items"][0]
    assert my_claim["pickup_location"] == "Security office, Block B"
    assert my_claim["handover_status"] == "awaiting_pickup"
    assert (await admin.get("/admin/stats"))["awaiting_pickup"] == 2

    # Collection closes everything.
    collected = await bob.post(f"/claims/{claim['id']}/collected")
    assert collected["handover_status"] == "collected" and not collected["can_message"]
    assert (await bob.get(f"/items/{found['id']}"))["status"] == "resolved"
    assert (await alice.get(f"/items/{lost_a['id']}"))["status"] == "resolved"
    assert any(n["title"] == "Item collected" for n in await notifications(alice))
    await alice.post(f"/claims/{claim['id']}/collected", expect=409)
    await alice.post(f"/claims/{claim['id']}/messages", expect=409, json={"body": "thanks"})

    logs = (await admin.get("/admin/audit-logs"))["items"]
    approval = next(entry for entry in logs if entry["action"].startswith("Approved claim"))
    assert "Security office, Block B" in approval["details"]


async def test_admin_resolving_a_claimed_report_records_collection(users, db):
    carol, eve, admin = users["carol"], users["eve"], users["admin"]
    lost = await carol.post("/lost-items", expect=201, json=lost_payload(item_name="Red umbrella", color="Red"))
    await approve(admin, lost["id"])
    claim = await eve.post(f"/items/{lost['id']}/claims", expect=201, json={"evidence_text": "Found it at the gym"})
    await admin.patch(f"/admin/claims/{claim['id']}", json={"status": "approved", "pickup_location": "Gym front desk"})
    await admin.patch(f"/admin/reports/{lost['id']}/status", json={"status": "resolved"})
    detail = await eve.get(f"/claims/{claim['id']}")
    assert detail["handover_status"] == "collected" and detail["collected_at"]

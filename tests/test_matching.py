from api.v1.services.matching import MATCH_THRESHOLD, item_pair_score

from .conftest import approve, found_payload, lost_payload, make_image, png_bytes, upload_photo


def item(**fields):
    return {"category": "Bags", "color": "Black", "location": "Main Library", "date": "2026-10-04", **fields}


def test_photo_less_reports_match_on_strong_metadata_only():
    perfect = item_pair_score(item(), item(image_hash="ffff0000ffff0000"))
    assert perfect >= MATCH_THRESHOLD
    loose = item_pair_score(item(), item(location="Sports Centre", date="2026-10-12"))
    assert loose < MATCH_THRESHOLD
    # A real photo match still beats a metadata-only one.
    both = item_pair_score(item(image_hash="ffff0000ffff0000"), item(image_hash="ffff0000ffff0000"))
    assert both > perfect


async def test_lost_report_without_photo_is_matched_and_notified(users):
    alice, bob, admin = users["alice"], users["bob"], users["admin"]
    photo = await upload_photo(bob, "found", seed=31)
    found = await bob.post("/found-items", expect=201, json=found_payload(photo, date_found="2026-10-04"))
    lost = await alice.post("/lost-items", expect=201, json=lost_payload())
    await approve(admin, found["id"])
    await approve(admin, lost["id"])
    assert (await alice.get(f"/items/{lost['id']}"))["status"] == "matched"


async def test_photo_search_ranks_the_right_item_first_and_skips_photo_less_items(users):
    alice, bob, eve, admin = users["alice"], users["bob"], users["eve"], users["admin"]
    ids = {}
    for seed in (41, 42, 43):
        photo = await upload_photo(bob, "found", seed=seed)
        report = await bob.post("/found-items", expect=201, json=found_payload(photo, item_name=f"Item {seed}"))
        await approve(admin, report["id"])
        ids[seed] = report["id"]
    no_photo = await alice.post("/lost-items", expect=201, json=lost_payload(item_name="Photo-less"))
    await approve(admin, no_photo["id"])

    # Same picture, resized and slightly darkened, as a user's own photo would be.
    query = make_image(42).resize((180, 180)).point(lambda value: int(value * 0.9))
    results = await eve.post(
        "/items/search/image",
        files={"file": ("query.png", png_bytes(query), "image/png")},
        data={"category": "Bags"},
    )
    assert results["items"][0]["id"] == ids[42]
    assert no_photo["id"] not in [r["id"] for r in results["items"]]

    bad = await eve.http.post(
        "/items/search/image",
        headers=eve.headers,
        files={"file": ("x.png", b"not an image", "image/png")},
    )
    assert bad.status_code == 415

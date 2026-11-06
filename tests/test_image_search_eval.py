"""Image-search evaluation on a generated dataset (spec §18).

Each "item" is a distinct synthetic picture photographed four ways: as-is, smaller,
darker and re-saved as a lower-quality JPEG with a slight crop. A good image search
should rank the other photos of the same item first.
"""

import io

from PIL import Image

from scripts.evaluate_image_search import evaluate

from .conftest import make_image, png_bytes


def jpeg_bytes(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def variants(seed: int) -> list[bytes]:
    base = make_image(seed)
    w, h = base.size
    return [
        png_bytes(base),
        png_bytes(base.resize((w // 2, h // 2))),
        png_bytes(base.point(lambda value: int(value * 0.8))),
        jpeg_bytes(base.crop((6, 6, w - 6, h - 6)), quality=60),
    ]


def test_image_search_finds_other_photos_of_the_same_item():
    groups = {f"item-{seed}": variants(seed) for seed in range(100, 130)}
    result = evaluate(groups, ks=(1, 3))
    print(f"\nimage search on {len(groups)} items / {result['queries']} queries: {result}")
    assert result["queries"] == 120
    assert result["top1"] >= 0.9
    assert result["top3"] >= 0.95
    assert result["precision@3"] >= 0.8

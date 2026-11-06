"""Evaluate image-search quality (top-K success rate / Precision@K).

Organise a test set as one sub-folder per physical item, each holding two or more
photos of that item (different angle, lighting, background...):

    dataset/
      black-backpack/  front.jpg  side.jpg  table.jpg
      blue-bottle/     1.png      2.png
      ...

Every photo is used once as a query against all the *other* photos. A query
succeeds at K when a photo of the same item appears in the top K results.

    uv run python -m scripts.evaluate_image_search dataset/ --k 1 3 5
"""

import argparse
import sys
from pathlib import Path

from api.v1.utils.image_hash import _dhash, image_similarity

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def evaluate(groups: dict[str, list[bytes]], ks: tuple[int, ...] = (1, 3, 5)) -> dict[str, float]:
    """Return ``{"top1": rate, "precision@1": p, ...}`` over every query photo.

    ``topK`` is the share of queries with at least one correct photo in the top K.
    ``precision@K`` is the average share of the top K that are correct.
    """
    photos = [(label, _dhash(data)) for label, items in groups.items() for data in items]
    hits = {k: 0 for k in ks}
    precision = {k: 0.0 for k in ks}
    queries = 0
    for index, (label, query_hash) in enumerate(photos):
        if sum(1 for other, _ in photos if other == label) < 2:
            continue  # nothing to find for an item with a single photo
        queries += 1
        ranked = sorted(
            ((image_similarity(query_hash, h) or 0.0, other) for j, (other, h) in enumerate(photos) if j != index),
            key=lambda pair: pair[0],
            reverse=True,
        )
        for k in ks:
            top = [other for _, other in ranked[:k]]
            hits[k] += label in top
            precision[k] += sum(other == label for other in top) / k
    if not queries:
        raise ValueError("Need at least one item with two or more photos")
    result = {f"top{k}": hits[k] / queries for k in ks}
    result.update({f"precision@{k}": precision[k] / queries for k in ks})
    result["queries"] = queries
    return result


def load_dataset(root: Path) -> dict[str, list[bytes]]:
    groups: dict[str, list[bytes]] = {}
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        photos = [f.read_bytes() for f in sorted(folder.iterdir()) if f.suffix.lower() in IMAGE_SUFFIXES]
        if photos:
            groups[folder.name] = photos
    return groups


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--k", type=int, nargs="+", default=[1, 3, 5])
    args = parser.parse_args()
    groups = load_dataset(args.dataset)
    result = evaluate(groups, tuple(args.k))
    print(f"{len(groups)} items, {result.pop('queries')} queries")
    for name, value in result.items():
        print(f"  {name:>12}: {value:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

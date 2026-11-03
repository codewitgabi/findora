import re
from datetime import date
from typing import Any, Optional

from api.v1.utils.image_hash import image_similarity

# Ranking signals. Weights are relative: signals that are not available for a
# comparison are dropped and the rest are re-normalised. Tune by testing.
WEIGHTS = {"image": 0.5, "category": 0.2, "color": 0.1, "location": 0.1, "date": 0.1}
# Item-to-item scores at or above this are surfaced as a "possible match".
MATCH_THRESHOLD = 0.75
# Minimum score for an item to be listed as similar or returned by photo search.
MIN_SIMILAR_SCORE = 0.4
MIN_SEARCH_SCORE = 0.3
# Days apart after which a lost/found date pair stops contributing any agreement.
_DATE_WINDOW_DAYS = 14


def hybrid_score(signals: dict[str, Optional[float]]) -> float:
    """Weighted average (0-1) of the signals that are present (not ``None``)."""
    present = {name: value for name, value in signals.items() if value is not None}
    total_weight = sum(WEIGHTS[name] for name in present)
    if not total_weight:
        return 0.0
    return sum(WEIGHTS[name] * value for name, value in present.items()) / total_weight


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def location_agreement(a: str, b: str) -> float:
    tokens_a, tokens_b = _tokens(a), _tokens(b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def date_agreement(a: str, b: str) -> float:
    try:
        days = abs((date.fromisoformat(a) - date.fromisoformat(b)).days)
    except ValueError:
        return 0.0
    return max(0.0, 1 - days / _DATE_WINDOW_DAYS)


def _same(a: str, b: str) -> float:
    return 1.0 if a.strip().lower() == b.strip().lower() else 0.0


def item_pair_score(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Score how likely a lost report and a found report describe the same object."""
    return hybrid_score(
        {
            "image": image_similarity(a.get("image_hash"), b.get("image_hash")),
            "category": _same(a["category"], b["category"]),
            "color": _same(a["color"], b["color"]),
            "location": location_agreement(a["location"], b["location"]),
            "date": date_agreement(a["date"], b["date"]),
        }
    )


def search_score(
    query_hash: str,
    item: dict[str, Any],
    *,
    category: Optional[str] = None,
    color: Optional[str] = None,
    location: Optional[str] = None,
    anchor_date: Optional[str] = None,
) -> float:
    """Score an item against a photo query plus whichever filters the user gave."""
    return hybrid_score(
        {
            "image": image_similarity(query_hash, item.get("image_hash")),
            "category": _same(category, item["category"]) if category else None,
            "color": _same(color, item["color"]) if color else None,
            "location": location_agreement(location, item["location"]) if location else None,
            "date": date_agreement(anchor_date, item["date"]) if anchor_date else None,
        }
    )

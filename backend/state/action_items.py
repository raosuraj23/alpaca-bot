"""
Shared module-level cache for Haiku-generated portfolio action items.
Both main.py (writer) and portfolio_director.py (reader) import from here
to avoid circular imports.
"""

_cache: dict = {"items": [], "generated_at": 0.0}


def set_items(items: list[dict], generated_at: float) -> None:
    _cache["items"] = items
    _cache["generated_at"] = generated_at


def get_items() -> list[dict]:
    return _cache.get("items", [])


def get_generated_at() -> float:
    return _cache.get("generated_at", 0.0)

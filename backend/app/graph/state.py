"""Graph state. Plain dicts only, so the checkpointer can serialise it."""
from typing import TypedDict


class SearchState(TypedDict, total=False):
    search_id: str
    device_type: str  # "camera" | ...
    raw_criteria: dict  # exactly what the form submitted
    criteria: dict  # validated by the device's criteria model
    queries: list[str]
    urls: list[str]
    pages: list[dict]  # {"url": ..., "text": ...}
    products: list[dict]  # extracted, device spec model dumped to dict
    candidates: list[dict]  # products that survived the filter
    ranked: list[dict]  # final, sorted by match_score
    attempts: int  # how many times queries have been planned
    error: str | None

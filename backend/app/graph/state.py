"""Graph state. Plain dicts only, so the checkpointer can serialise it."""
from typing import TypedDict


class SearchState(TypedDict, total=False):
    search_id: str
    device_type: str  # "camera" | ...
    raw_criteria: dict  # exactly what the form submitted
    criteria: dict  # validated by the device's criteria model
    queries: list[str]  # planned in the current attempt
    past_queries: list[str]  # every query planned so far, so retries don't repeat them
    urls: list[str]  # every unique URL found so far (grows across attempts)
    hits: list[dict]  # {url, title, snippet, score, query} for each URL
    pages: list[dict]  # {"url": ..., "text": ...}
    products: list[dict]  # extracted, device spec model dumped to dict
    candidates: list[dict]  # products that survived the filter
    dropped: list[dict]  # products removed by the filter, with reasons
    ranked: list[dict]  # final, sorted by match_score
    attempts: int  # how many times queries have been planned
    error: str | None

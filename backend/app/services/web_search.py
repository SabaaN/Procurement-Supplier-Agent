"""Web search through Tavily. Returns plain dicts so nodes and tests don't depend on the SDK."""
from functools import lru_cache

from ..config import settings


class SearchError(RuntimeError):
    """Anything that stopped a search: missing key, quota, network."""


@lru_cache(maxsize=1)
def _client():
    if not settings.tavily_api_key:
        raise SearchError("TAVILY_API_KEY is not set (add it to backend/.env)")
    from tavily import TavilyClient

    return TavilyClient(settings.tavily_api_key)


def search_web(query: str, max_results: int | None = None) -> list[dict]:
    """One Tavily search. Each hit: url, title, snippet, score."""
    try:
        response = _client().search(
            query=query,
            max_results=max_results or settings.results_per_query,
            search_depth="basic",
        )
    except SearchError:
        raise
    except Exception as e:  # SDK raises its own error types; we only need one
        raise SearchError(f"{type(e).__name__}: {e}") from e

    return [
        {
            "url": r["url"],
            "title": r.get("title", ""),
            "snippet": r.get("content", ""),
            "score": r.get("score"),
        }
        for r in response.get("results", [])
        if r.get("url")
    ]
"""Web search through Tavily. Returns plain dicts so nodes and tests don't depend on the SDK."""
import logging
from functools import lru_cache
from urllib.parse import urlsplit

from ..config import settings

log = logging.getLogger(__name__)


class SearchError(RuntimeError):
    """Anything that stopped a search: missing key, quota, network."""


@lru_cache(maxsize=1)
def _client():
    if not settings.tavily_api_key:
        raise SearchError("TAVILY_API_KEY is not set (add it to backend/.env)")
    from tavily import TavilyClient

    return TavilyClient(settings.tavily_api_key)


def search_web(query: str, max_results: int | None = None, country: str | None = None) -> list[dict]:
    """One Tavily search. Each hit: url, title, snippet, score.
    country (e.g. "pakistan") asks Tavily to prefer results from that country."""
    kwargs = dict(
        query=query,
        max_results=max_results or settings.results_per_query,
        search_depth="basic",
        exclude_domains=list(settings.skip_domains),
    )
    if country:
        kwargs["country"] = country
    try:
        try:
            response = _client().search(**kwargs)
        except TypeError:
            if "country" not in kwargs:
                raise
            # an older tavily-python without the country option: search without it (the queries and the
            # seller check still keep results to Pakistan)
            log.warning("This tavily-python version has no country option; upgrade it for better local results")
            kwargs.pop("country")
            response = _client().search(**kwargs)
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
        if r.get("url") and not is_skipped(r["url"])
    ]


def is_skipped(url: str) -> bool:
    """Video, social and encyclopedia sites: they don't sell the product, so reading them wastes a Groq call."""
    host = urlsplit(url).netloc.lower().split(":")[0].removeprefix("www.").removeprefix("m.")
    return any(host == d or host.endswith("." + d) for d in settings.skip_domains)
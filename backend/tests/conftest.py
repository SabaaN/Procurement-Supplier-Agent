"""Shared fixtures. Every test runs with Groq and Tavily faked, so no test touches the network."""
import pytest

from app.services import query_planner, web_search


@pytest.fixture(autouse=True)
def fake_services(monkeypatch):
    def fake_plan(device_key, criteria, attempt, previous=()):
        # 1 query on the first attempt, 2 on later ones (broader)
        n = 1 if attempt == 1 else 2
        return [f"query-{attempt}-{i}" for i in range(n)], "llm"

    def fake_search(query, max_results=None):
        # 3 unique pages per query
        return [
            {"url": f"https://example.com/{query}/{i}", "title": f"{query} #{i}", "snippet": "", "score": 1.0}
            for i in range(3)
        ]

    monkeypatch.setattr(query_planner, "plan", fake_plan)
    monkeypatch.setattr(web_search, "search_web", fake_search)
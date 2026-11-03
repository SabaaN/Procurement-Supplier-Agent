"""Shared fixtures. Every test runs with Groq, Tavily and page fetching faked, and a temp cache DB."""
import pytest

from app.services import cache, page_fetcher, query_planner, web_search


@pytest.fixture(autouse=True)
def fake_services(monkeypatch, tmp_path):
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

    def fake_fetch(url, client=None):
        return page_fetcher.FetchResult(url, True, text="stub page text " * 20)

    monkeypatch.setattr(query_planner, "plan", fake_plan)
    monkeypatch.setattr(web_search, "search_web", fake_search)
    monkeypatch.setattr(page_fetcher, "fetch_page", fake_fetch)
    monkeypatch.setattr(cache, "_db_path", lambda: tmp_path / "test.db")
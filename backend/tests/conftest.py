"""Shared fixtures. Every test runs with Groq, Tavily, page fetching and extraction faked, and a temp cache DB."""
import pytest
from app.devices.camera import CAMERA
from app.services import cache, explainer, extractor, fx, page_fetcher, query_planner, web_search

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

    ids = {}  # each new URL gets the next stub product (price 8000, 11000, 14000, ...)

    def fake_extract(device_key, url, title, text):
        i = ids.setdefault(url, len(ids))
        return CAMERA.stub_spec(i, url).model_dump(mode="json")

    def no_llm(facts):
        raise RuntimeError("LLM disabled in tests")

    monkeypatch.setattr(explainer, "_llm_explanations", no_llm) 

    monkeypatch.setattr(query_planner, "plan", fake_plan)
    monkeypatch.setattr(web_search, "search_web", fake_search)
    monkeypatch.setattr(page_fetcher, "fetch_page", fake_fetch)
    monkeypatch.setattr(extractor, "extract_product", fake_extract)
    monkeypatch.setattr(cache, "_db_path", lambda: tmp_path / "test.db")
    monkeypatch.setattr(fx, "_fetch_usd_rates", lambda: {"USD": 1.0, "PKR": 280.0, "EUR": 0.9})
    monkeypatch.setattr(fx, "_last_failure", None)
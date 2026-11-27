"""Shared fixtures. Every test runs with Groq, Tavily, page fetching and extraction faked, and a temp cache DB."""
import pytest
from app.devices import get_device
from app.services import cache, extractor, fx, llm, page_fetcher, query_planner, web_search

# What a fake product page says: a device name and a price, so the pre-model page check reads it.
PRODUCT_TEXT = "Stub product page for a camera / encoder / photoelectric sensor. Price Rs 9,000. " * 5

@pytest.fixture(autouse=True)
def fake_services(monkeypatch, tmp_path):
    llm.reset_limits()  # no model starts a test marked as out for the day
    # no per-minute pacing: fake calls cost nothing, and a test must never sleep (test_pacing turns it on)
    monkeypatch.setattr(llm.PACER, "limit", 0)
    def fake_plan(device_key, criteria, attempt, previous=()):
        # 1 query on the first attempt, 2 on later ones (broader)
        n = 1 if attempt == 1 else 2
        return [f"query-{attempt}-{i}" for i in range(n)], "llm"

    def fake_search(query, max_results=None, country=None):
        # 3 unique pages per query
        return [
            {"url": f"https://example.com/{query}/{i}", "title": f"{query} #{i}", "snippet": "", "score": 1.0}
            for i in range(3)
        ]

    def fake_fetch(url, client=None):
        return page_fetcher.FetchResult(url, True, text=PRODUCT_TEXT)

    ids = {}  # each new URL gets the next stub product (price 8000, 11000, 14000, ...)

    def fake_extract(device_key, url, title, text):
        i = ids.setdefault(url, len(ids))
        return get_device(device_key).stub_spec(i, url).model_dump(mode="json")


    monkeypatch.setattr(query_planner, "plan", fake_plan)
    monkeypatch.setattr(web_search, "search_web", fake_search)
    monkeypatch.setattr(page_fetcher, "fetch_page", fake_fetch)
    monkeypatch.setattr(extractor, "extract_product", fake_extract)

    def fake_extract_page(device_key, url, title, text):
        # goes through extract_product, so tests that patch that keep working
        product = extractor.extract_product(device_key, url, title, text)
        return ("product" if product else "other"), product

    monkeypatch.setattr(extractor, "extract_page", fake_extract_page)
    monkeypatch.setattr(cache, "_db_path", lambda: tmp_path / "test.db")
    monkeypatch.setattr(fx, "_fetch_usd_rates", lambda: {"USD": 1.0, "PKR": 280.0, "EUR": 0.9})
    monkeypatch.setattr(fx, "_last_failure", None)
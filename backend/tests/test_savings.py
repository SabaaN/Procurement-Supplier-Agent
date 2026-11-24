"""Fewer model calls: obvious pages are recognised in Python, less text is sent, readings are kept for days."""
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.devices import get_device
from app.graph import nodes
from app.services import cache, extractor
from app.services.page_fetcher import TABLES_HEADER, trim_text
from app.services.prices import page_prices
from app.services.triage import triage

CAM = get_device("camera")
PE = get_device("photoelectric")


def page(url="https://shop.test/p/cam-5mp", text="5 MP GigE camera. Price Rs 45,000.", **links):
    return {"url": url, "ok": True, "title": "", "text": text, "links": links}


# ---- the page check ----

@pytest.mark.parametrize("url", [
    "https://shop.test/blog/best-cameras-2026", "https://shop.test/news/new-sensors",
    "https://shop.test/guides/choosing-a-sensor", "https://shop.test/about-us", "https://shop.test/faq",
])
def test_blog_news_guide_and_company_pages_are_skipped(url):
    assert triage(CAM, page(url=url)) == "not_product"


@pytest.mark.parametrize("url", [
    "https://shop.test/products/guide-rail-camera", "https://shop.test/product/news-cam-5mp",
    "https://shop.test/p/12345",
])
def test_words_inside_a_product_address_do_not_count(url):
    assert triage(CAM, page(url=url)) is None


def test_a_page_with_no_device_words_and_no_price_is_skipped():
    assert triage(PE, page(text="Our company has served industry since 1990. Call us.")) == "not_product"


def test_a_device_word_or_a_price_is_enough_to_read_it():
    assert triage(PE, page(text="E3Z diffuse sensor, sensing distance 100 mm")) is None  # no price
    assert triage(PE, page(text="Model X-200. Price Rs 4,500.")) is None  # price, odd name
    assert triage(PE, page(text="Model X-200.", prices={"shown": ["Rs 4,500"], "data": []})) is None


def listing_page(**prices):
    return page(url="https://shop.test/sensors/", text="Photoelectric sensors - 24 items",
                products=[f"https://shop.test/product/s{i}/" for i in range(12)],
                prices={"shown": [], "data": [], **prices})


def test_shop_listings_are_recognised():
    assert triage(PE, listing_page(count=12, products=0)) == "listing"
    assert triage(PE, listing_page(count=12, products=12)) == "listing"  # an ItemList


def test_a_product_page_with_related_products_is_not_a_listing():
    assert triage(PE, listing_page(count=12, products=1)) is None  # embedded data: exactly one product
    assert triage(PE, listing_page(count=2, products=0)) is None  # few prices: one product and its tiers
    assert triage(PE, listing_page()) is None  # cached before prices were counted: read it


def test_price_reader_counts_prices_and_products():
    cards = "".join(f'<div class="card"><a href="/product/s{i}/">Sensor {i}</a>'
                    f'<span class="price">Rs {1000 + i * 100}</span></div>' for i in range(10))
    item_list = ('<script type="application/ld+json">{"@type":"ItemList","itemListElement":'
                 '[{"@type":"ListItem"},{"@type":"ListItem"},{"@type":"ListItem"}]}</script>')
    p = page_prices(f"<html><head>{item_list}</head><body>{cards}</body></html>")
    assert p["count"] == 10 and len(p["shown"]) == 6 and p["products"] == 3  # shown is capped, count is not

    single = ('<script type="application/ld+json">{"@type":"Product","name":"E3Z",'
              '"offers":{"@type":"Offer","price":"4500","priceCurrency":"PKR"}}</script>')
    assert page_prices(single)["products"] == 1


def test_listings_are_followed_and_obvious_pages_skipped_without_model_calls(monkeypatch):
    calls = []

    def read(device_key, url, title, text):
        calls.append(url)
        return "product", {"title": url, "source_url": url}

    monkeypatch.setattr(extractor, "extract_page", read)
    listing = {**listing_page(count=12, products=0), "ok": True}
    links = listing["links"]["products"]
    fetched = {u: {"url": u, "ok": True, "title": "", "text": "Diffuse photoelectric sensor. Rs 3,000.",
                   "links": {"prices": {"shown": ["Rs 3,000"], "data": [], "count": 1, "products": 1}}}
               for u in links}
    monkeypatch.setattr(nodes, "_fetch", lambda urls, titles, label="pages": [fetched[u] for u in urls])
    events = []
    monkeypatch.setattr(nodes, "emit", lambda *a, **k: events.append(a))

    state = {"device_type": "photoelectric", "urls": [], "pages": [
        listing, page(url="https://shop.test/blog/how-sensors-work", text="photoelectric sensors explained")]}
    out = nodes.extract(state)
    assert calls == links[: settings.listing_links_per_page]  # only the product pages reached the model
    assert len(out["products"]) == settings.listing_links_per_page
    assert "1 skipped without a model call" in events[-1][2] and "1 listing pages" in events[-1][2]


# ---- less text per page ----

def test_trimming_keeps_the_spec_tables():
    text = "description " * 2000 + TABLES_HEADER + "\n".join(f"Spec {i} | value {i}" for i in range(40))
    out = trim_text(text, 6000)
    assert len(out) <= 6000 and "Spec 39 | value 39" in out and out.startswith("description")


def test_short_descriptions_leave_more_room_for_tables():
    tables = "\n".join(f"Spec {i} | value {i}" for i in range(400))
    out = trim_text("Short description." + TABLES_HEADER + tables, 6000)
    assert len(out) <= 6000 and out.startswith("Short description.") and out.count("|") > 200


def test_pages_cached_at_the_old_size_are_trimmed_before_the_model(monkeypatch):
    seen = []

    def read(device_key, url, title, text):
        seen.append(text)
        return "other", None

    monkeypatch.setattr(extractor, "extract_page", read)
    big = page(text="camera " * 3000, prices={"shown": ["Rs 45,000"], "data": [], "count": 1, "products": 1})
    nodes._extract_pages("camera", [big])
    body, _, prices = seen[0].partition("\n\nPrices shown on the page:")
    assert len(body) == settings.max_page_chars and "Rs 45,000" in prices


# ---- readings kept for days ----

def test_readings_are_reused_for_days_then_read_again(monkeypatch):
    key, url = extractor.cache_key("camera"), "https://shop.test/p/cam-5mp"
    calls = []
    monkeypatch.setattr(extractor, "extract_page",
                        lambda *a: calls.append(a[1]) or ("product", {"title": "new", "source_url": a[1]}))

    def saved(days_ago):
        cache.put_extraction(url, key, {"title": "old", "source_url": url}, "product")
        when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        with cache._connect() as conn:
            conn.execute("UPDATE extraction_cache SET fetched_at = ? WHERE url = ?", (when, url))

    saved(3)
    out, *_ = nodes._extract_pages("camera", [page()])
    assert out[0][2]["title"] == "old" and calls == []  # 3 days old: no model call

    saved(8)
    out, *_ = nodes._extract_pages("camera", [page()])
    assert out[0][2]["title"] == "new" and calls == [url]  # older than 7 days: read again


def test_defaults():
    assert settings.max_page_chars == 6000 and settings.extraction_cache_hours == 7 * 24
    assert settings.cache_ttl_hours == 24  # downloads still refresh daily: no model call needed

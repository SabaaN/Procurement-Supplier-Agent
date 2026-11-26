"""Shipping time: read from the page in Python, so it costs no model call and no tokens."""
import csv
import io

import httpx
import pytest
from fastapi.testclient import TestClient

from app.devices import get_device
from app.graph import nodes
from app.main import app
from app.services import cache, extractor, page_fetcher
from app.services.shipping import find

from .conftest import PRODUCT_TEXT

REAL_FETCH = page_fetcher.fetch_page  # captured before the autouse fakes replace it


@pytest.mark.parametrize("html, want", [
    ("<p>Delivery: 3-5 working days</p>", "Delivery: 3-5 working days"),
    ("<div>Ships in 2 weeks</div>", "Ships in 2 weeks"),
    ("<td>Lead time</td><td>4-6 weeks</td>", "Lead time 4-6 weeks"),  # label and value in two cells
    ("<p>Dispatched within 24 hours</p>", "Dispatched within 24 hours"),
    ("<p>Delivery time</p><p>2 - 4 business days</p>", "Delivery time 2 - 4 business days"),
    ("<p>Same day delivery in Karachi</p>", "Same day delivery"),
    ("<p>2-3 days delivery all over Pakistan</p>", "2-3 days delivery"),
    ("<p>Ready to ship: in stock, ships next day</p>", "Ready to ship: in stock, ships next day"),
    ("<p>Estimated delivery: 5–7 days</p><p>Lead time: 3 weeks</p>", "Lead time: 3 weeks"),  # the product's own
])
def test_delivery_times_are_found_as_written(html, want):
    assert find(html) == want


@pytest.mark.parametrize("html", [
    "<p>7 days return policy</p><p>1 year warranty</p>",  # not shipping
    "<p>14 days return, free delivery</p>",
    "<p>Free shipping on orders over Rs 5,000</p>",  # no duration
    "<p>Order placed 3 days ago</p>",
    "<p>Omron E3Z sensor, 100 mm, response 1 ms</p>",
    "<p>Delivery nationwide. Response time 1 ms</p>",  # a duration, but not a delivery time
    "<script>var delivery = '2 days'</script><p>PLC CPU</p>",  # scripts are not the page
])
def test_no_delivery_time_leaves_it_empty(html):
    assert find(html) is None


def test_fetch_page_records_it():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "text/html"},
                              text=f"<html><body><p>{PRODUCT_TEXT}</p><p>Delivery: 2-3 working days</p></body></html>")

    r = REAL_FETCH("https://shop.test/p/1", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert r.ok and r.links["shipping"] == "Delivery: 2-3 working days"


def test_cached_readings_get_it_from_todays_page_without_a_model_call(monkeypatch):
    monkeypatch.setattr(extractor, "extract_page", lambda *a: pytest.fail("no model call"))
    url = "https://shop.test/p/1"
    cache.put_extraction(url, extractor.cache_key("camera"), {"title": "cam", "source_url": url}, "product")
    page = {"url": url, "ok": True, "title": "", "text": PRODUCT_TEXT, "links": {"shipping": "Ships in 2 weeks"}}
    out, *_ = nodes._extract_pages("camera", [page])
    assert out[0][2]["shipping_time"] == "Ships in 2 weeks"
    old = {**page, "links": {}}  # downloaded before shipping was read: empty until the next download
    out, *_ = nodes._extract_pages("camera", [old])
    assert out[0][2]["shipping_time"] is None


@pytest.mark.parametrize("device", ["camera", "encoder", "photoelectric", "plc"])
def test_the_model_is_not_asked_for_it(device):
    """No extra tokens: shipping is not in any extraction schema or instruction."""
    d = get_device(device)
    assert not any("ship" in f or "deliver" in f for f in d.extraction_model.model_fields)
    assert "shipping" not in d.extraction_hint.lower() and "delivery" not in d.extraction_hint.lower()
    assert "shipping" not in extractor.SYSTEM.lower()


def test_csv_has_the_column_blank_when_unknown(monkeypatch):
    def fetch(url, client=None):
        links = {"shipping": "Delivery: 3-5 working days"} if url.endswith("/0") else {}
        return page_fetcher.FetchResult(url, True, text=PRODUCT_TEXT, links=links)

    monkeypatch.setattr(page_fetcher, "fetch_page", fetch)
    client = TestClient(app)
    sid = client.post("/api/searches", json={"device_type": "camera", "criteria": {}}).json()["id"]
    rows = list(csv.reader(io.StringIO(client.get(f"/api/searches/{sid}/export.csv").text.lstrip("﻿"))))
    col = rows[0].index("Shipping time")
    values = [r[col] for r in rows[1:]]
    assert "Delivery: 3-5 working days" in values and "" in values

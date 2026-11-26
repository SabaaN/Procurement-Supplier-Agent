"""'Search Pakistan market only': searches target Pakistan, and only sellers that show they are there stay."""
import csv
import io

import pytest
from fastapi.testclient import TestClient

from app.devices import get_device
from app.devices.base import SharedCriteria
from app.graph import nodes
from app.main import app
from app.services import extractor, page_fetcher, query_planner, web_search
from app.services.pakistan import evidence, page_evidence
from app.services.triage import triage

from .conftest import PRODUCT_TEXT

REAL_SEARCH = web_search.search_web  # captured before the autouse fakes replace it


# ---- the evidence ----

@pytest.mark.parametrize("url, text, links, currency, want", [
    ("https://shop.pk/p/1", "Omron sensor", {}, None, [".pk website"]),
    ("https://automation.com.pk/x", "", {}, None, [".pk website"]),
    ("https://example.com/p", "Call 0300-1234567", {}, None, ["Pakistani phone number"]),
    ("https://example.com/p", "", {"phones": ["+92 21 3456 7890"]}, None, ["Pakistani phone number"]),
    ("https://example.com/p", "Price: Rs 4,500", {}, None, ["price in PKR"]),
    ("https://example.com/p", "", {}, "PKR", ["price in PKR"]),
    ("https://example.com/p", "Showroom: Hall Road, Lahore", {}, None, ["address in Lahore"]),
    ("https://daraz.pk/products/x", "Rs. 12,000", {}, "PKR", [".pk website", "price in PKR"]),
])
def test_pakistani_sellers_are_recognised(url, text, links, currency, want):
    assert evidence(url, text, links, currency) == want


@pytest.mark.parametrize("url, text", [
    ("https://example.in/p", "Price: Rs. 4,500"),  # Indian rupees
    ("https://example.com/p", "Rs 4,500. Call +91 98765 43210"),
    ("https://example.com/p", "₹4,500 incl. GST, Rs 4,500"),
    ("https://alibaba.com/p", "We ship worldwide, including to Pakistan. US$45"),  # shipping there isn't being there
    ("https://example.com/p", "Model 5000. Call +1 555 0100"),
])
def test_foreign_sellers_show_no_evidence(url, text):
    assert evidence(url, text) == []


# ---- the flag ----

def test_flag_defaults_off_and_reaches_the_criteria():
    assert SharedCriteria().pakistan_only is False
    client = TestClient(app)
    sid = client.post("/api/searches", json={"device_type": "camera",
                                             "criteria": {"pakistan_only": True}}).json()["id"]
    assert client.get(f"/api/searches/{sid}").json()["criteria"]["pakistan_only"] is True


# ---- searching ----

def test_tavily_is_asked_for_pakistan_and_older_versions_still_work(monkeypatch):
    seen = []

    class New:
        def search(self, **kw):
            seen.append(kw)
            return {"results": []}

    class Old:
        def search(self, query, max_results, search_depth, exclude_domains):  # no country option
            seen.append("old")
            return {"results": []}

    monkeypatch.setattr(web_search, "_client", lambda: New())
    REAL_SEARCH("PLC price", country="pakistan")
    REAL_SEARCH("PLC price")
    assert seen[0]["country"] == "pakistan" and "country" not in seen[1]

    monkeypatch.setattr(web_search, "_client", lambda: Old())
    assert REAL_SEARCH("PLC price", country="pakistan") == [] and seen[-1] == "old"


def test_the_search_step_passes_the_flag(monkeypatch):
    countries = []
    monkeypatch.setattr(web_search, "search_web", lambda q, max_results=None, country=None: countries.append(country) or [])
    nodes.search({"queries": ["a", "b"], "criteria": {"pakistan_only": True}})
    nodes.search({"queries": ["c"], "criteria": {}})
    assert countries == ["pakistan", "pakistan", None]


@pytest.mark.parametrize("device", ["camera", "encoder", "photoelectric", "plc"])
def test_every_fallback_query_names_pakistan(device):
    d = get_device(device)
    crit = {"currency": "USD", "pakistan_only": True}
    qs = query_planner.fallback_queries(d, query_planner.spec_items(d, crit), 1, crit)
    assert qs and all("Pakistan" in q or "Karachi" in q for q in qs)


def test_the_planner_is_told_pakistan_only():
    d = get_device("plc")
    crit = {"currency": "USD", "pakistan_only": True}
    prompt = query_planner._prompt(d, query_planner.spec_items(d, crit), crit, 1, [])
    assert "Only sellers in Pakistan: EVERY query" in prompt
    off = query_planner._prompt(d, [], {"currency": "USD"}, 1, [])
    assert "Pakistan" not in off


# ---- reading and filtering ----

def foreign(url="https://shop.example.com/p/1"):
    return {"url": url, "ok": True, "title": "", "text": "PLC CPU, 14 DI. US$290. Call +1 555 0100", "links": {}}


def local(url="https://shop.pk/p/2"):
    return {"url": url, "ok": True, "title": "", "text": PRODUCT_TEXT, "links": {"phones": ["0300-1234567"]}}


def test_foreign_pages_are_skipped_before_the_model_only_when_asked():
    plc = get_device("plc")
    assert triage(plc, foreign(), pakistan_only=True) == "not_pakistan"
    assert triage(plc, local(), pakistan_only=True) is None
    assert triage(plc, foreign()) is None  # flag off: read as before


def test_extraction_skips_foreign_pages_and_records_the_evidence(monkeypatch):
    calls = []
    monkeypatch.setattr(extractor, "extract_page",
                        lambda d, url, t, x: calls.append(url) or ("product", {"title": url, "source_url": url}))
    events = []
    monkeypatch.setattr(nodes, "emit", lambda *a, **k: events.append(a))
    out = nodes.extract({"device_type": "plc", "criteria": {"pakistan_only": True},
                         "pages": [foreign(), local()], "urls": []})
    assert calls == ["https://shop.pk/p/2"]
    assert out["products"][0]["pakistan_evidence"] == [".pk website", "Pakistani phone number", "price in PKR"]
    assert "1 skipped: seller not in Pakistan" in events[-1][2]


def test_filter_drops_sellers_without_evidence_only_when_asked():
    products = [{"title": "pk", "pakistan_evidence": [".pk website"]}, {"title": "abroad", "pakistan_evidence": []}]
    on = nodes.filter_products({"device_type": "plc", "criteria": {"pakistan_only": True}, "products": products})
    assert [p["title"] for p in on["candidates"]] == ["pk"]
    assert on["dropped"][0]["reasons"] == ["No sign the seller is in Pakistan"]
    off = nodes.filter_products({"device_type": "plc", "criteria": {}, "products": products})
    assert len(off["candidates"]) == 2


def test_foreign_sellers_are_never_offered_as_closest_matches():
    c = {"pakistan_only": True, "min_digital_inputs": {"value": 16, "required": True}}
    products = [
        {"title": "abroad, 24 DI", "digital_inputs": 24, "pakistan_evidence": []},
        {"title": "pk, 14 DI", "digital_inputs": 14, "pakistan_evidence": ["price in PKR"]},
    ]
    state = {"device_type": "plc", "criteria": c, "products": products}
    state.update(nodes.filter_products(state))
    assert state["candidates"] == []
    assert [p["title"] for p in nodes.score(state)["candidates"]] == ["pk, 14 DI"]


# ---- a whole search through the API ----

def test_pakistan_only_search_end_to_end(monkeypatch):
    def fetch(url, client=None):
        foreign_page = url.endswith(("/1", "/3", "/5", "/7", "/9"))
        text = "PLC CPU. US$290. Call +1 555 0100" if foreign_page else PRODUCT_TEXT
        return page_fetcher.FetchResult(url, True, text=text, links={})

    monkeypatch.setattr(page_fetcher, "fetch_page", fetch)
    client = TestClient(app)
    sid = client.post("/api/searches", json={"device_type": "plc", "criteria": {
        "currency": "PKR", "pakistan_only": True}}).json()["id"]
    products = client.get(f"/api/searches/{sid}/results").json()["products"]
    assert products and all(p["pakistan_evidence"] for p in products)

    rows = list(csv.reader(io.StringIO(client.get(f"/api/searches/{sid}/export.csv").text.lstrip("﻿"))))
    col = rows[0].index("Seller in Pakistan")
    assert all("price in PKR" in r[col] for r in rows[1:])

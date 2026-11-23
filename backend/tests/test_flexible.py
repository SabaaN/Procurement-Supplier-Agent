"""Flexible specs and budget, cheaper-than-minimum products, listing pages, wrong product types,
closest matches, and shop-style search queries."""
import pytest
from fastapi.testclient import TestClient

from app.devices import get_device
from app.devices.camera import CameraCriteria, CameraExtraction
from app.graph import nodes, scoring
from app.graph.checks import check_product
from app.main import app
from app.services import cache, extractor, page_fetcher, query_planner

from .test_extraction import FakeLLM

real_extract_page = extractor.extract_page  # before the autouse fixture swaps in a fake
real_plan = query_planner.plan


def cam(**kw):
    base = dict(title="cam", source_url="https://s.test/p", price=120000, currency="PKR",
                megapixels=5.0, fps=30.0, shutter="global", interface=["GigE"])
    return {**base, **kw}


# ---- the Flexible level ----

def test_flexible_wins_over_required():
    c = CameraCriteria.model_validate({"min_fps": {"value": 30, "required": True, "flexible": True}})
    assert c.min_fps.flexible and not c.min_fps.required


FLEX = {"min_megapixels": {"value": 5, "required": False, "flexible": True},
        "shutter": {"value": "global", "required": False, "flexible": True}}


def test_flexible_number_close_is_kept_and_far_is_dropped():
    close = check_product(FLEX, cam(megapixels=4.2), tolerance=0.2)
    assert close["dropped_for"] == [] and close["close"] == ["Resolution"]
    assert close["close_notes"] == ["Resolution: 4.2 MP, close to your 5 MP"]

    far = check_product(FLEX, cam(megapixels=3.0), tolerance=0.2)
    assert far["dropped_for"] == ["Resolution: 3 MP, too far below 5 MP"]

    above = check_product(FLEX, cam(megapixels=12.0))
    assert "Resolution" in above["met"]  # 12 MP is more than asked: a full match


def test_flexible_choice_that_differs_is_a_compromise_not_a_drop():
    v = check_product(FLEX, cam(shutter="rolling"))
    assert v["dropped_for"] == [] and "Shutter type" in v["close"]
    assert "Shutter type: rolling instead of global" in v["close_notes"]


def test_must_have_still_drops():
    v = check_product({"min_fps": {"value": 30, "required": True}}, cam(fps=25.0))
    assert v["dropped_for"] == ["Frame rate: does not meet requirement"]


def test_close_matches_rank_below_full_matches():
    c = {**FLEX, "budget_min": None, "budget_max": None}
    out = nodes.filter_products({"criteria": c, "products": [cam(title="close", megapixels=4.5), cam(title="full")]})
    scores = {p["title"]: p["match_score"] for p in scoring.score_products(c, out["candidates"])}
    assert scores["full"] > scores["close"]
    close = next(p for p in out["candidates"] if p["title"] == "close")
    assert close["requirements_close"] == ["Resolution"] and close["close_notes"]


# ---- budget ----

def budget(**kw):
    return {"budget_min": 100000, "budget_max": 150000, "currency": "PKR", **kw}


def test_flexible_budget_keeps_a_little_over_and_flags_it():
    products = [cam(title="10% over", price=165000), cam(title="30% over", price=195000)]
    out = nodes.filter_products({"criteria": budget(flexible_budget=True), "products": products})
    assert [p["title"] for p in out["candidates"]] == ["10% over"]
    assert "10% over budget" in out["candidates"][0]["flags"]
    assert out["dropped"][0]["reasons"] == ["Price above budget (30% over)"]

    strict = nodes.filter_products({"criteria": budget(), "products": products})
    assert strict["candidates"] == []


def test_below_minimum_is_kept_but_earns_no_extra_price_credit():
    c = budget()
    out = nodes.filter_products({"criteria": c, "products": [cam(title="cheap", price=20000),
                                                             cam(title="at floor", price=100000)]})
    assert {p["title"] for p in out["candidates"]} == {"cheap", "at floor"}
    cheap = next(p for p in out["candidates"] if p["title"] == "cheap")
    assert any("unusually cheap" in f for f in cheap["flags"])
    scored = {p["title"]: p["score_breakdown"]["price"] for p in scoring.score_products(c, out["candidates"])}
    assert scored["cheap"] == scored["at floor"]  # 20,000 is treated as 100,000 for ranking


# ---- closest matches ----

def test_nothing_matches_so_the_closest_are_returned_marked():
    c = {**budget(), "min_fps": {"value": 30, "required": True}}
    products = [cam(title="slow", fps=20.0), cam(title="dear", price=400000), cam(title="dear and slow", price=400000, fps=10.0)]
    state = {"criteria": c, "products": products, **nodes.filter_products({"criteria": c, "products": products})}
    assert state["candidates"] == []
    out = nodes.score(state)["candidates"]
    assert [p["title"] for p in out][-1] == "dear and slow"  # two misses: the furthest away
    assert all(p["near_miss"] for p in out)
    assert next(p for p in out if p["title"] == "slow")["misses"] == ["Frame rate: does not meet requirement"]
    worst = next(p for p in out if p["title"] == "dear and slow")
    assert worst["match_score"] < min(p["match_score"] for p in out if p is not worst)

    ranked = nodes.finalize({"criteria": c, "candidates": list(reversed(out)), "device_type": "camera"})["ranked"]
    assert ranked[-1]["title"] == "dear and slow"  # fewest misses first, whatever the score


def test_closest_matches_reach_the_api_and_csv(monkeypatch):
    client = TestClient(app)
    sid = client.post("/api/searches", json={"device_type": "camera", "criteria": {"budget_max": 100}}).json()["id"]
    products = client.get(f"/api/searches/{sid}/results").json()["products"]
    assert products and all(p["near_miss"] for p in products)  # every stub costs 8000+
    csv_text = client.get(f"/api/searches/{sid}/export.csv").text
    assert "Not an exact match because" in csv_text and "Price above budget" in csv_text


def test_api_accepts_flexible_criteria():
    client = TestClient(app)
    r = client.post("/api/searches", json={"device_type": "camera", "criteria": {
        "min_megapixels": {"value": 5, "flexible": True}, "flexible_budget": True, "budget_max": 150000}})
    assert r.status_code == 202


# ---- what kind of page it is ----

@pytest.mark.parametrize("fields, kind", [
    (dict(is_product_page=True, is_right_device_type=False, title="Hikvision bullet"), "wrong_type"),
    (dict(is_product_page=False, is_listing_page=True), "listing"),
    (dict(is_product_page=False), "other"),
    (dict(is_product_page=True, is_right_device_type=True, title="Basler ace"), "product"),
])
def test_extract_page_kinds(monkeypatch, fields, kind):
    monkeypatch.setattr(extractor, "_llm", lambda *a: FakeLLM([CameraExtraction(**fields)]))
    got_kind, product = real_extract_page("camera", "https://a.test/p", "", "some page text")
    assert got_kind == kind and (product is not None) == (kind == "product")


def test_listing_pages_are_followed_one_level(monkeypatch):
    listing = "https://shop.test/cameras/"
    links = {"products": [f"https://shop.test/product/cam-{i}/" for i in range(10)]}

    def fetch(url, client=None):
        return page_fetcher.FetchResult(url, True, text="page text " * 30, links=links if url == listing else {})

    def page(device_key, url, title, text):
        if url == listing:
            return "listing", None
        if url == "https://shop.test/other":
            return "wrong_type", None
        return "product", cam(title=url, source_url=url)

    monkeypatch.setattr(page_fetcher, "fetch_page", fetch)
    monkeypatch.setattr(extractor, "extract_page", page)
    monkeypatch.setattr(nodes.settings.__class__, "listing_links_per_page", property(lambda s: 4))

    state = {"device_type": "camera", "urls": [listing, "https://shop.test/other"], "hits": []}
    state = {**state, **nodes.fetch_clean(state)}
    out = nodes.extract(state)
    titles = sorted(p["title"] for p in out["products"])
    assert titles == [f"https://shop.test/product/cam-{i}/" for i in range(4)]  # capped at 4 per listing
    assert set(links["products"][:4]) <= set(out["urls"])  # remembered, so not read twice

    # a further attempt (only when results are still thin) takes the listing's next links, never the same ones
    again = nodes.extract({**state, **out})
    assert sorted(p["title"] for p in again["products"]) == sorted(links["products"][:8])
    assert len({p["url"] for p in again["pages"]}) == len(again["pages"])


def test_extraction_cache_keeps_the_kind():
    key = extractor.cache_key("camera")
    cache.put_extraction("https://a.test/l", key, None, "listing")
    assert cache.get_extraction("https://a.test/l", key) == {"product": None, "kind": "listing"}


# ---- search queries ----

def items(criteria):
    return query_planner.spec_items(get_device("camera"), criteria)


def test_fallback_queries_are_shop_style_without_flexible_numbers():
    crit = {"currency": "PKR", "min_megapixels": {"value": 5, "required": True},
            "min_fps": {"value": 30, "required": False, "flexible": True}}
    qs = query_planner.fallback_queries(get_device("camera"), items(crit), 1, crit)
    assert qs[0] == "machine vision camera 5 MP price in Pakistan"  # machine vision first, local shops
    assert any("digital camera" in q for q in qs)  # then other kinds of camera too
    assert all("30" not in q and "datasheet" not in q for q in qs)


def test_prompt_steers_away_from_cctv_and_keeps_flexible_out():
    crit = {"currency": "PKR", "min_fps": {"value": 30, "required": False, "flexible": True}}
    text = query_planner._prompt(get_device("camera"), items(crit), crit, 1, [])
    assert "CCTV" in text and "price in Pakistan" in text
    assert "Flexible specs" in text and "- Frame rate: about 30 fps" in text


def test_planner_falls_back_when_groq_is_unavailable(monkeypatch):
    monkeypatch.setattr(query_planner.settings.__class__, "groq_api_key", property(lambda s: ""))
    queries, source = real_plan("camera", {"currency": "USD"}, 1)
    assert source.startswith("fallback") and queries[0] == "machine vision camera price"
    assert "industrial camera price" in queries


def test_budget_order_error_names_a_field_the_form_can_highlight():
    client = TestClient(app)
    r = client.post("/api/searches", json={"device_type": "camera",
                                           "criteria": {"budget_min": 150000, "budget_max": 100000}})
    assert r.status_code == 422
    assert r.json()["detail"] == [{"field": "budget_max", "message": "Budget max must be at least Budget min"}]


def test_exact_matches_rank_above_cheaper_close_matches():
    c = {**FLEX, "budget_min": None, "budget_max": None}
    products = [cam(title="close but cheap", megapixels=4.5, price=50000), cam(title="exact but dearer", price=140000)]
    out = nodes.filter_products({"criteria": c, "products": products})
    scored = scoring.score_products(c, out["candidates"])
    ranked = nodes.finalize({"criteria": c, "candidates": scored, "device_type": "camera"})["ranked"]
    assert [p["title"] for p in ranked] == ["exact but dearer", "close but cheap"]

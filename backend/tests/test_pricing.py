import pytest

from app.graph import nodes, scoring
from app.services import fx


# ---- exchange rates ----

def test_rates_go_through_usd():
    assert fx.get_rate("USD", "PKR") == 280.0
    assert fx.get_rate("EUR", "PKR") == pytest.approx(280.0 / 0.9)
    assert fx.get_rate("PKR", "PKR") == 1.0
    assert fx.get_rate("XYZ", "PKR") is None


def test_rates_are_cached_in_the_database(monkeypatch):
    calls = []
    monkeypatch.setattr(fx, "_fetch_usd_rates", lambda: calls.append(1) or {"USD": 1.0, "PKR": 280.0})
    fx.get_rate("USD", "PKR")
    fx.get_rate("USD", "PKR")
    assert len(calls) == 1


def test_failed_download_is_not_retried_straight_away(monkeypatch):
    calls = []
    monkeypatch.setattr(fx, "_fetch_usd_rates", lambda: calls.append(1))  # returns None = failure
    assert fx.get_rate("USD", "PKR") is None
    assert fx.get_rate("USD", "PKR") is None
    assert len(calls) == 1


# ---- convert_prices node ----

def test_convert_prices_converts_and_totals():
    state = {
        "criteria": {"currency": "PKR", "quantity": 4},
        "products": [
            {"title": "usd", "price": 100.0, "currency": "USD", "flags": []},
            {"title": "pkr", "price": 5000.0, "currency": "PKR", "flags": []},
            {"title": "unknown", "price": 10.0, "currency": None, "flags": []},
            {"title": "nofx", "price": 10.0, "currency": "XYZ", "flags": []},
            {"title": "noprice", "price": None, "currency": "USD", "flags": []},
        ],
    }
    out = {p["title"]: p for p in nodes.convert_prices(state)["products"]}
    assert out["usd"]["price_buyer"] == 28000.0 and out["usd"]["fx_rate"] == 280.0
    assert out["usd"]["total_cost"] == 112000.0
    assert out["pkr"]["price_buyer"] == 5000.0 and out["pkr"]["fx_rate"] is None
    assert out["pkr"]["total_cost"] == 20000.0
    assert out["unknown"]["price_buyer"] == 10.0
    assert out["nofx"]["price_buyer"] is None and out["nofx"]["total_cost"] is None
    assert out["noprice"]["price_buyer"] is None


def test_moq_above_quantity_is_flagged():
    state = {
        "criteria": {"currency": "PKR", "quantity": 4},
        "products": [{"title": "a", "price": 1.0, "currency": "PKR", "moq": 10, "flags": []}],
    }
    product = nodes.convert_prices(state)["products"][0]
    assert "MOQ 10 is above your quantity 4" in product["flags"]


def test_filter_uses_the_converted_price_for_the_budget():
    state = {
        "criteria": {"budget_max": 20000, "currency": "PKR"},
        "products": [
            {"title": "cheap-usd", "price": 50.0, "currency": "USD", "price_buyer": 14000.0},
            {"title": "dear-usd", "price": 100.0, "currency": "USD", "price_buyer": 28000.0},
            {"title": "no-rate", "price": 5.0, "currency": "XYZ", "price_buyer": None},
        ],
    }
    out = nodes.filter_products(state)
    assert [p["title"] for p in out["candidates"]] == ["cheap-usd", "no-rate"]
    assert any("no exchange rate" in f for f in out["candidates"][1]["flags"])


# ---- scoring ----

def product(title, price_buyer, met=(), flags=()):
    return {"title": title, "price_buyer": price_buyer, "requirements_met": list(met), "flags": list(flags)}


def test_better_match_and_lower_price_score_higher():
    crit = {"min_fps": {"value": 30.0, "required": False}, "interface": {"value": ["GigE"], "required": False}}
    products = [
        product("both", 200, met=["Frame rate", "Interface"]),
        product("one", 100, met=["Frame rate"]),
        product("none", 300),
    ]
    s = {p["title"]: p for p in scoring.score_products(crit, products)}
    assert s["both"]["score_breakdown"]["preferences"] == 1.0
    assert s["one"]["score_breakdown"]["preferences"] == 0.5
    assert (s["both"]["match_score"], s["one"]["match_score"], s["none"]["match_score"]) == (85.0, 75.0, 20.0)


def test_without_preferences_the_weight_moves_to_price_and_confidence():
    s = {p["title"]: p for p in scoring.score_products({}, [product("cheap", 100), product("dear", 300)])}
    assert s["cheap"]["score_breakdown"]["preferences"] is None
    assert s["cheap"]["match_score"] == 100.0 and s["dear"]["match_score"] == 40.0


def test_flags_lower_confidence_and_a_missing_price_scores_zero_on_price():
    s = {p["title"]: p for p in scoring.score_products(
        {}, [product("flagged", 100, flags=["a", "b"]), product("noprice", None)])}
    assert s["flagged"]["score_breakdown"]["confidence"] == 0.5
    assert s["noprice"]["score_breakdown"]["price"] == 0.0
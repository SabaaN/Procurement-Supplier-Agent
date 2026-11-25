"""Node tests that need no LangGraph: nodes are plain functions over a state dict."""
from app.graph import nodes


def run_device_pipeline(state: dict) -> dict:
    """What the device subgraph does, written as a plain loop."""
    while True:
        for step in (nodes.plan_queries, nodes.search, nodes.fetch_clean, nodes.extract, nodes.filter_products):
            state = {**state, **step(state)}
        if nodes.route_after_filter(state) == "score":
            return {**state, **nodes.score(state)}


def start(raw: dict, device="camera") -> dict:
    state = {"device_type": device, "raw_criteria": raw}
    return {**state, **nodes.parse_requirements(state)}


def test_parse_ok():
    s = start({"min_megapixels": {"value": 5, "required": True}, "budget_max": 20000})
    assert s["error"] is None
    assert s["criteria"]["min_megapixels"] == {"value": 5.0, "required": True, "flexible": False}
    assert nodes.route_device(s) == "camera"


def test_parse_bad_value_routes_to_error():
    s = start({"shutter": {"value": "electronic"}})
    assert s["error"] and "shutter" in s["error"]
    assert nodes.route_device(s) == "error"


def test_parse_unsupported_device_routes_to_error():
    s = start({}, device="hmi")
    assert "not supported" in s["error"]
    assert nodes.route_device(s) == "error"


def test_filter_applies_budget_and_flags_missing_price():
    state = {
        "criteria": {"budget_min": 10000, "budget_max": 20000},
        "products": [
            {"title": "cheap", "price": 4000},
            {"title": "ok", "price": 15000},
            {"title": "dear", "price": 30000},
            {"title": "unknown", "price": None},
        ],
    }
    out = nodes.filter_products(state)
    kept = {p["title"]: p for p in out["candidates"]}
    assert list(kept) == ["cheap", "ok", "unknown"]  # cheaper than the minimum is fine
    assert any("unusually cheap" in f for f in kept["cheap"]["flags"])  # 4000 < half of 10000
    assert not any("unusually cheap" in f for f in kept["ok"]["flags"])
    assert "price_missing" in kept["unknown"]["flags"]
    assert out["dropped"][0]["title"] == "dear" and out["dropped"][0]["reasons"] == ["Price above budget (50% over)"]


def test_loop_broadens_search_when_too_few_survive():
    s = run_device_pipeline(start({"budget_max": 20000}))
    assert s["attempts"] == 2  # first pass found 3 < MIN_RESULTS, second found enough
    assert len(s["candidates"]) >= nodes.MIN_RESULTS


def test_loop_stops_at_max_attempts():
    s = run_device_pipeline(start({"budget_max": 9000}))  # only one stub product ever fits
    assert s["attempts"] == nodes.MAX_ATTEMPTS
    assert len(s["candidates"]) < nodes.MIN_RESULTS


def test_finalize_sorts_by_score_then_price():
    state = {
        "candidates": [
            {"title": "a", "match_score": 50, "price": 300},
            {"title": "b", "match_score": 80, "price": 500},
            {"title": "c", "match_score": 50, "price": 100},
        ]
    }
    assert [p["title"] for p in nodes.finalize(state)["ranked"]] == ["b", "c", "a"]

def run_device_pipeline(state: dict) -> dict:
    """What the device subgraph does, written as a plain loop."""
    while True:
        for step in (nodes.plan_queries, nodes.search, nodes.fetch_clean, nodes.extract,
                     nodes.convert_prices, nodes.filter_products):
            state = {**state, **step(state)}
        if nodes.route_after_filter(state) == "score":
            return {**state, **nodes.score(state)}
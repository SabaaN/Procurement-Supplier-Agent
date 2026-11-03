from app.graph import nodes
from app.graph.checks import check_product

CRIT = {
    "min_megapixels": {"value": 5.0, "required": True},
    "shutter": {"value": "global", "required": True},
    "min_fps": {"value": 30.0, "required": False},
    "interface": {"value": ["GigE", "USB3"], "required": False},
}


def product(**kw):
    return {"title": "p", "price": 1000, "megapixels": 5.0, "fps": 60.0,
            "shutter": "global", "interface": ["GigE"], **kw}


def test_all_met():
    v = check_product(CRIT, product())
    assert v["dropped_for"] == [] and v["missed"] == []
    assert set(v["met"]) == {"Resolution", "Shutter type", "Frame rate", "Interface"}


def test_required_miss_drops():
    v = check_product(CRIT, product(shutter="rolling"))
    assert v["dropped_for"] == ["Shutter type: does not meet requirement"]


def test_required_missing_data_drops_and_is_not_guessed():
    v = check_product(CRIT, product(megapixels=None))
    assert v["dropped_for"] == ["Resolution: not found on page"]
    assert "Resolution" in v["unknown"]


def test_preferred_miss_or_unknown_never_drops():
    v = check_product(CRIT, product(fps=10.0, interface=[]))
    assert v["dropped_for"] == []
    assert "Frame rate" in v["missed"] and "Interface" in v["unknown"]


def test_interface_any_overlap():
    v = check_product(CRIT, product(interface=["CoaxPress", "USB3"]))
    assert "Interface" in v["met"]


def test_filter_node_records_drops_and_keeps_verdicts():
    state = {
        "criteria": {**CRIT, "budget_min": None, "budget_max": 2000},
        "products": [
            product(title="good"),
            product(title="rolling", shutter="rolling"),
            product(title="dear", price=5000),
            product(title="slow", fps=10.0),
        ],
    }
    out = nodes.filter_products(state)
    assert [p["title"] for p in out["candidates"]] == ["good", "slow"]
    assert {d["title"] for d in out["dropped"]} == {"rolling", "dear"}
    slow = out["candidates"][1]
    assert slow["requirements_missed"] == ["Frame rate"]
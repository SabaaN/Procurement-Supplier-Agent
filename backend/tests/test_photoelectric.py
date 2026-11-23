"""The photoelectric sensor device: criteria, normalisation, its checks, search wording, and a full search."""
import csv
import io

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.devices import get_device
from app.devices.parse import length_mm, time_ms
from app.devices.photoelectric import (
    PHOTOELECTRIC_CHECKS, PhotoelectricCriteria, PhotoelectricExtraction, normalize_photoelectric,
)
from app.graph import nodes
from app.graph.checks import check_product
from app.main import app
from app.services import extractor, query_planner

from .test_extraction import FakeLLM

real_extract_page = extractor.extract_page  # captured before the autouse fakes replace it
PE = get_device("photoelectric")


def sensor(**kw):
    base = dict(title="sensor", source_url="https://s.test/p", price=3500, currency="PKR",
                sensing_method="diffuse", sensing_range_mm=300.0, output=["NPN"],
                switching_mode=["light-on", "dark-on"], light_source="red", housing="M18", connection="cable",
                supply_min_v=10.0, supply_max_v=30.0, response_time_ms=1.0, ip_rating=67)
    return {**base, **kw}


def check(criteria, product, **kw):
    return check_product(criteria, product, checks=PE.checks, units=PE.units, **kw)


# ---- criteria and form ----

def test_form_fields_map_to_criteria():
    fields = {f.name for f in PE.fields}
    assert fields <= set(PhotoelectricCriteria.model_fields)
    assert set(PHOTOELECTRIC_CHECKS) <= fields


def test_criteria_validate():
    c = PhotoelectricCriteria.model_validate({
        "sensing_method": {"value": "through-beam", "required": True},
        "output": {"value": ["PNP", "IO-Link"]},
        "min_sensing_range": {"value": 2000},
    })
    assert c.sensing_method.required and c.output.value == ["PNP", "IO-Link"]
    with pytest.raises(ValidationError):
        PhotoelectricCriteria.model_validate({"housing": {"value": "M10"}})


# ---- units: the model copies, Python converts ----

@pytest.mark.parametrize("text, mm", [
    ("0.1-2 m", 2000), ("300mm", 300), ("20 cm", 200), ("2 m (with reflector)", 2000),
    ("10~800 mm", 800), ("1,5 m", 1500), ("30 to 200 mm adjustable", 200), ("up to 20m", 20000),
    ("200", None),  # no unit: not guessed
])
def test_sensing_distance_to_mm(text, mm):
    assert length_mm(text) == mm


@pytest.mark.parametrize("text, ms", [
    ("1 ms max.", 1), ("≤ 500 μs", 0.5), ("500us", 0.5), ("0.5ms", 0.5), ("Operate/reset: 1 ms each", 1),
    ("fast", None),
])
def test_response_time_to_ms(text, ms):
    assert time_ms(text) == ms


# ---- normalisation ----

@pytest.mark.parametrize("text, want", [
    ("Polarized retro-reflective", "polarized retro-reflective"), ("Retro-reflective (with reflector)", "retro-reflective"),
    ("Mirror reflection", "retro-reflective"), ("Through-beam (emitter + receiver)", "through-beam"),
    ("Diffuse reflective", "diffuse"), ("Background suppression (BGS)", "background suppression"),
    ("Fiber optic", "fiber optic"), ("Proximity type", "diffuse"),
])
def test_sensing_methods(text, want):
    assert normalize_photoelectric({"sensing_method": text})[0]["sensing_method"] == want


@pytest.mark.parametrize("text, want", [
    ("Light-ON / Dark-ON selectable", ["light-on", "dark-on"]), ("L/D switchable", ["light-on", "dark-on"]),
    ("Light-on", ["light-on"]), ("Dark ON", ["dark-on"]), ("D.ON", ["dark-on"]), (None, []),
])
def test_switching_modes(text, want):
    assert normalize_photoelectric({"switching_mode": text})[0]["switching_mode"] == want


def test_outputs_light_housing_connection():
    out, flags = normalize_photoelectric({
        "output": ["NPN/PNP selectable", "IO-Link"], "light_source": "Red LED (660 nm)",
        "housing": "M18 cylindrical, nickel-plated brass", "connection": "M12 4-pin connector",
        "supply_min_v": 30, "supply_max_v": 10, "ip_rating": "IP67", "sensing_range": "4 m",
        "response_time": "0.5 ms",
    })
    assert out["output"] == ["NPN", "PNP", "IO-Link"]
    assert (out["light_source"], out["housing"], out["connection"]) == ("red", "M18", "M12 connector")
    assert (out["supply_min_v"], out["supply_max_v"], out["ip_rating"]) == (10, 30, 67)
    assert (out["sensing_range_mm"], out["response_time_ms"]) == (4000, 0.5) and flags == []


@pytest.mark.parametrize("text, want", [
    ("Infrared LED (880 nm)", "infrared"), ("Red laser, class 1", "laser"), ("IR", "infrared"),
    ("Blue LED", "blue"), ("red LED", "red"),
])
def test_light_sources(text, want):
    assert normalize_photoelectric({"light_source": text})[0]["light_source"] == want


def test_unknown_values_stay_empty_and_are_flagged():
    out, flags = normalize_photoelectric({"housing": "round", "sensing_range": "long", "output": ["magic"]})
    assert out["housing"] is None and out["sensing_range_mm"] is None and out["output"] == []
    assert len(flags) == 3


# ---- the sensor's checks ----

def test_selectable_switching_satisfies_either_mode():
    c = {"switching_mode": {"value": "dark-on", "required": True}}
    assert check(c, sensor())["met"] == ["Light-on / dark-on"]  # selectable
    assert check(c, sensor(switching_mode=["light-on"]))["dropped_for"]
    assert check(c, sensor(switching_mode=[]))["unknown"] == ["Light-on / dark-on"]


def test_distance_minimum_response_time_maximum():
    c = {"min_sensing_range": {"value": 2000, "required": True}, "max_response_time": {"value": 1, "required": True}}
    v = check(c, sensor(sensing_range_mm=4000.0, response_time_ms=0.5))
    assert v["met"] == ["Sensing distance", "Response time"]
    v = check(c, sensor(sensing_range_mm=300.0, response_time_ms=2.0))
    assert len(v["dropped_for"]) == 2


def test_flexible_distance_and_response_time():
    c = {"min_sensing_range": {"value": 2000, "flexible": True}, "max_response_time": {"value": 1, "flexible": True}}
    v = check(c, sensor(sensing_range_mm=1800.0, response_time_ms=1.1), tolerance=0.2)
    assert v["close_notes"] == ["Sensing distance: 1800 mm, close to your 2000 mm",
                                "Response time: 1.1 ms, close to your 1 ms"]


def test_supply_voltage_range():
    c = {"supply_voltage": {"value": 24, "required": True}}
    assert check(c, sensor())["met"] == ["Supply voltage"]
    assert check(c, sensor(supply_min_v=90.0, supply_max_v=250.0))["dropped_for"]  # AC-only sensor


def test_filter_uses_the_sensor_checks():
    c = {"housing": {"value": "M12", "required": True}, "budget_min": None, "budget_max": None}
    out = nodes.filter_products({"device_type": "photoelectric", "criteria": c,
                                 "products": [sensor(title="m18"), sensor(title="m12", housing="M12")]})
    assert [p["title"] for p in out["candidates"]] == ["m12"]


# ---- reading pages ----

def test_proximity_sensors_are_the_wrong_kind(monkeypatch):
    llm = FakeLLM([PhotoelectricExtraction(is_product_page=True, is_right_device_type=False,
                                           title="Inductive proximity sensor M18")])
    monkeypatch.setattr(extractor, "_llm", lambda *a: llm)
    assert real_extract_page("photoelectric", "https://s.test/i", "", "inductive sensor") == ("wrong_type", None)


def test_a_sensor_page_becomes_a_product(monkeypatch):
    raw = PhotoelectricExtraction(is_product_page=True, is_right_device_type=True, title="Omron E3Z-D61",
                                  sensing_method="Diffuse-reflective", sensing_range="5 to 100 mm",
                                  output=["NPN open collector"], switching_mode="Light-ON/Dark-ON selectable",
                                  response_time="1 ms max.", supply_min_v=12, supply_max_v=24, ip_rating="IP67")
    monkeypatch.setattr(extractor, "_llm", lambda *a: FakeLLM([raw]))
    kind, p = real_extract_page("photoelectric", "https://s.test/e3z", "", "Omron E3Z-D61 diffuse 100 mm")
    assert kind == "product"
    assert (p["sensing_method"], p["sensing_range_mm"], p["output"]) == ("diffuse", 100, ["NPN"])
    assert p["switching_mode"] == ["light-on", "dark-on"] and p["response_time_ms"] == 1


# ---- search wording ----

def test_queries_say_photoelectric_sensor():
    crit = {"currency": "PKR", "sensing_method": {"value": "through-beam", "required": True},
            "min_sensing_range": {"value": 2000, "required": False, "flexible": True}}
    items = query_planner.spec_items(PE, crit)
    qs = query_planner.fallback_queries(PE, items, 1, crit)
    assert qs[0] == "photoelectric sensor through-beam price in Pakistan"
    assert all("2000" not in q for q in qs)
    prompt = query_planner._prompt(PE, items, crit, 1, [])
    assert "proximity sensors" in prompt and "Sensing distance: about 2000 mm" in prompt


# ---- a whole search through the API ----

def test_a_sensor_search_runs_end_to_end():
    client = TestClient(app)
    devices = {d["key"]: d for d in client.get("/api/devices").json()}
    assert devices["photoelectric"]["enabled"] and devices["photoelectric"]["label"] == "Photoelectric sensor"
    assert "sensor" not in devices

    sid = client.post("/api/searches", json={"device_type": "photoelectric", "criteria": {
        "currency": "PKR", "supply_voltage": {"value": 24, "required": True},
        "switching_mode": {"value": "light-on", "required": True}}}).json()["id"]
    products = client.get(f"/api/searches/{sid}/results").json()["products"]
    assert products and all("light-on" in p["switching_mode"] for p in products)  # dark-on-only stubs dropped
    assert all(p["supply_min_v"] <= 24 <= p["supply_max_v"] for p in products)

    rows = list(csv.reader(io.StringIO(client.get(f"/api/searches/{sid}/export.csv").text.lstrip("﻿"))))
    assert {"sensing_method", "sensing_range_mm", "output", "switching_mode", "response_time_ms"} <= set(rows[0])
    assert "megapixels" not in rows[0] and "ppr" not in rows[0]

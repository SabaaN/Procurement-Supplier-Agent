"""The rotary encoder device: criteria, normalisation, its own checks, search wording, and a full search."""
import csv
import io

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.devices import get_device
from app.devices.encoder import ENCODER_CHECKS, EncoderCriteria, EncoderExtraction, normalize_encoder
from app.graph import nodes
from app.graph.checks import check_product
from app.main import app
from app.services import extractor, query_planner

from .test_extraction import FakeLLM

real_extract_page = extractor.extract_page  # captured before the autouse fakes replace it
ENC = get_device("encoder")


def enc(**kw):
    base = dict(title="enc", source_url="https://s.test/e", price=20000, currency="PKR", encoder_type="incremental",
                ppr=1024, output=["TTL (RS-422)"], shaft_type="solid", shaft_diameter_mm=6.0,
                housing_diameter_mm=58.0, supply_min_v=10.0, supply_max_v=30.0, max_rpm=6000, ip_rating=65)
    return {**base, **kw}


def check(criteria, product, **kw):
    return check_product(criteria, product, checks=ENC.checks, units=ENC.units, **kw)


# ---- criteria and form ----

def test_form_fields_map_to_criteria():
    fields = {f.name for f in ENC.fields}
    assert fields <= set(EncoderCriteria.model_fields)
    assert set(ENCODER_CHECKS) <= fields  # every check can be set from the form


def test_criteria_validate():
    c = EncoderCriteria.model_validate({
        "encoder_type": {"value": "absolute", "required": True},
        "output": {"value": ["SSI", "BiSS"]},
        "supply_voltage": {"value": 24},
    })
    assert c.encoder_type.required and c.output.value == ["SSI", "BiSS"]
    with pytest.raises(ValidationError):
        EncoderCriteria.model_validate({"output": {"value": ["Firewire"]}})
    with pytest.raises(ValidationError):
        EncoderCriteria.model_validate({"min_ppr": {"value": -5}})


# ---- normalisation ----

@pytest.mark.parametrize("text, want", [
    ("TTL / RS-422 line driver", ["TTL (RS-422)"]),
    ("HTL push-pull 10-30V", ["HTL (push-pull)"]),
    ("NPN open collector, PNP", ["NPN open collector", "PNP"]),
    ("SSI + BiSS-C", ["SSI", "BiSS"]),
    ("Sin/Cos 1Vpp", ["Sin/Cos 1 Vpp"]),
    ("4-20 mA analog", ["Analog"]),
    ("Classic aluminium housing", []),  # 'ssi' inside 'classic' is not SSI
])
def test_outputs_are_recognised(text, want):
    assert normalize_encoder({"output": [text]})[0]["output"] == want


def test_normalisation_does_the_arithmetic_and_tidies_ranges():
    out, flags = normalize_encoder({
        "singleturn_steps": 8192, "supply_min_v": 30, "supply_max_v": 10,
        "ip_rating": "IP 67 / IP65", "shaft_type": "Blind hollow shaft", "max_rpm": 12000,
    })
    assert out["resolution_bits"] == 13 and out["encoder_type"] == "absolute"  # bits imply absolute
    assert (out["supply_min_v"], out["supply_max_v"]) == (10, 30)
    assert out["ip_rating"] == 67 and out["shaft_type"] == "blind hollow" and flags == []


def test_unknown_values_stay_empty_and_are_flagged():
    out, flags = normalize_encoder({"encoder_type": "magnetic", "ip_rating": "sealed", "singleturn_steps": 1000})
    assert out["encoder_type"] is None and out["ip_rating"] is None
    assert out["resolution_bits"] is None  # 1000 steps is not a whole number of bits: not guessed
    assert any("encoder_type" in f for f in flags) and any("ip_rating" in f for f in flags)


@pytest.mark.parametrize("text, want", [
    ("Hollow shaft", "hollow"), ("through bore", "hollow"), ("blind hollow shaft", "blind hollow"),
    ("solid shaft", "solid"), ("hub shaft", "blind hollow"),
])
def test_shaft_types(text, want):
    assert normalize_encoder({"shaft_type": text})[0]["shaft_type"] == want


# ---- the encoder's own checks ----

def test_supply_voltage_must_fall_inside_the_range():
    c = {"supply_voltage": {"value": 24, "required": True}}
    assert check(c, enc())["met"] == ["Supply voltage"]
    assert check(c, enc(supply_min_v=5.0, supply_max_v=5.0))["dropped_for"] == ["Supply voltage: does not meet requirement"]
    assert check(c, enc(supply_max_v=None))["unknown"] == ["Supply voltage"]


def test_housing_is_a_maximum_and_flexible_allows_a_little_more():
    must = {"max_housing_diameter": {"value": 58, "required": True}}
    assert check(must, enc(housing_diameter_mm=50.0))["met"] == ["Housing diameter"]
    assert check(must, enc(housing_diameter_mm=66.0))["dropped_for"]

    flex = {"max_housing_diameter": {"value": 58, "flexible": True, "required": False}}
    close = check(flex, enc(housing_diameter_mm=66.0), tolerance=0.2)
    assert close["close_notes"] == ["Housing diameter: 66 mm, close to your 58 mm"]
    far = check(flex, enc(housing_diameter_mm=80.0), tolerance=0.2)
    assert far["dropped_for"] == ["Housing diameter: 80 mm, too far above 58 mm"]


def test_shaft_diameter_output_and_ppr():
    c = {"shaft_diameter": {"value": 6, "required": True}, "output": {"value": ["HTL (push-pull)", "TTL (RS-422)"]},
         "min_ppr": {"value": 2000, "flexible": True, "required": False}}
    v = check(c, enc(ppr=1800))
    assert "Shaft / bore diameter" in v["met"] and "Output" in v["met"] and v["close"] == ["Resolution (PPR)"]
    assert check(c, enc(ppr=1800, shaft_diameter_mm=10.0))["dropped_for"] == ["Shaft / bore diameter: does not meet requirement"]


def test_filter_uses_the_encoder_checks_not_the_camera_ones():
    c = {"min_ip": {"value": 67, "required": True}, "budget_min": None, "budget_max": None}
    out = nodes.filter_products({"device_type": "encoder", "criteria": c,
                                 "products": [enc(title="ip65"), enc(title="ip67", ip_rating=67)]})
    assert [p["title"] for p in out["candidates"]] == ["ip67"]
    assert out["dropped"][0]["reasons"] == ["IP rating: does not meet requirement"]


# ---- reading pages ----

def test_video_encoders_are_the_wrong_kind_of_product(monkeypatch):
    llm = FakeLLM([EncoderExtraction(is_product_page=True, is_right_device_type=False, title="H.264 HDMI encoder")])
    monkeypatch.setattr(extractor, "_llm", lambda *a: llm)
    assert real_extract_page("encoder", "https://s.test/v", "", "HDMI video encoder") == ("wrong_type", None)


def test_an_encoder_page_becomes_a_product(monkeypatch):
    raw = EncoderExtraction(is_product_page=True, is_right_device_type=True, title="Kubler 5000 incremental",
                            encoder_type="Incremental", ppr=1024, output=["RS422 (TTL)"], shaft_type="solid shaft",
                            shaft_diameter_mm=6, supply_min_v=5, supply_max_v=30, ip_rating="IP64")
    monkeypatch.setattr(extractor, "_llm", lambda *a: FakeLLM([raw]))
    kind, p = real_extract_page("encoder", "https://s.test/k", "", "Kubler 5000 incremental 1024 ppr RS422")
    assert kind == "product"
    assert (p["ppr"], p["output"], p["shaft_type"], p["ip_rating"]) == (1024, ["TTL (RS-422)"], "solid", 64)


# ---- search wording ----

def test_queries_say_rotary_encoder_and_steer_away_from_video_encoders():
    crit = {"currency": "PKR", "max_housing_diameter": {"value": 58, "required": True},
            "min_ppr": {"value": 1024, "required": False, "flexible": True}}
    items = query_planner.spec_items(ENC, crit)
    qs = query_planner.fallback_queries(ENC, items, 1, crit)
    assert qs[0] == "industrial rotary encoder 58 mm price in Pakistan"
    assert all("1024" not in q for q in qs)  # flexible: left out of the searches
    prompt = query_planner._prompt(ENC, items, crit, 1, [])
    assert "video encoders" in prompt and "Housing diameter: at most 58 mm" in prompt


# ---- a whole search through the API ----

def test_an_encoder_search_runs_end_to_end():
    client = TestClient(app)
    devices = {d["key"]: d for d in client.get("/api/devices").json()}
    assert devices["encoder"]["enabled"]
    form = client.get("/api/devices/encoder").json()
    assert any(f["name"] == "supply_voltage" for f in form["fields"])

    sid = client.post("/api/searches", json={"device_type": "encoder", "criteria": {
        "currency": "PKR", "supply_voltage": {"value": 24, "required": True},
        "shaft_type": {"value": "solid"}}}).json()["id"]
    products = client.get(f"/api/searches/{sid}/results").json()["products"]
    assert products and all(p["supply_min_v"] <= 24 <= p["supply_max_v"] for p in products)  # 5 V-only stubs dropped
    assert all(p.get("encoder_type") for p in products)

    rows = list(csv.reader(io.StringIO(client.get(f"/api/searches/{sid}/export.csv").text.lstrip("﻿"))))
    assert {"ppr", "output", "shaft_type", "supply_min_v", "ip_rating"} <= set(rows[0])
    assert "megapixels" not in rows[0]

"""The PLC device: criteria, normalisation, its checks, search wording, and a full search."""
import csv
import io

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.devices import get_device
from app.devices.parse import frequency_khz
from app.devices.plc import PLC_CHECKS, PlcCriteria, PlcExtraction, normalize_plc
from app.graph import nodes
from app.graph.checks import check_product
from app.main import app
from app.services import extractor, query_planner

from .test_extraction import FakeLLM

real_extract_page = extractor.extract_page  # captured before the autouse fakes replace it
PLC = get_device("plc")


def plc(**kw):
    base = dict(title="plc", source_url="https://s.test/p", price=60000, currency="PKR", brand="Siemens",
                series="S7-1200", plc_type="compact", digital_inputs=14, digital_outputs=10,
                output_type=["transistor (source / PNP)"], analog_inputs=2, analog_outputs=0, supply=["24 V DC"],
                communication=["Ethernet", "PROFINET"], hsc_khz=100.0, pulse_axes=4, expandable=True)
    return {**base, **kw}


def check(criteria, product, **kw):
    return check_product(criteria, product, checks=PLC.checks, units=PLC.units, **kw)


# ---- criteria and form ----

def test_form_fields_map_to_criteria():
    fields = {f.name for f in PLC.fields}
    assert fields <= set(PlcCriteria.model_fields) and set(PLC_CHECKS) <= fields


def test_criteria_validate():
    c = PlcCriteria.model_validate({"plc_type": {"value": "compact", "required": True},
                                    "communication": {"value": ["Ethernet", "RS-485"]}})
    assert c.communication.value == ["Ethernet", "RS-485"]
    with pytest.raises(ValidationError):
        PlcCriteria.model_validate({"plc_type": {"value": "rack-mount"}})
    with pytest.raises(ValidationError):
        PlcCriteria.model_validate({"min_digital_inputs": {"value": 0}})


# ---- normalisation ----

@pytest.mark.parametrize("brand, title, want", [
    ("SIEMENS SIMATIC", "", "Siemens"), (None, "S7-1200 CPU 1214C DC/DC/DC", "Siemens"),
    ("", "LOGO! 8 12/24RCE", "Siemens"), ("Mitsubishi Electric", "", "Mitsubishi"),
    (None, "FX5U-32MR/ES", "Mitsubishi"), ("Rockwell Automation", "", "Allen-Bradley"),
    (None, "Micro850 2080-LC50-24QWB", "Allen-Bradley"), (None, "Delta DVP14SS211R", "Delta"),
    (None, "Modicon M221", "Schneider"), ("LS Electric", "", "LS"), (None, "XGB XBC-DR14E", "LS"),
    (None, "Generic controller", None),
])
def test_brands(brand, title, want):
    assert normalize_plc({"brand": brand, "title": title})[0]["brand"] == want


@pytest.mark.parametrize("text, want", [
    ("Relay", ["relay"]), ("Transistor (sink)", ["transistor (sink / NPN)"]),
    ("PNP transistor, sourcing", ["transistor (source / PNP)"]),
    ("8 relay + 2 transistor NPN", ["relay", "transistor (sink / NPN)"]),
])
def test_output_types(text, want):
    assert normalize_plc({"output_type": text})[0]["output_type"] == want


def test_transistor_without_sink_or_source_is_flagged_not_guessed():
    out, flags = normalize_plc({"output_type": "Transistor"})
    assert out["output_type"] == [] and flags == ["transistor outputs: sink or source not stated"]


@pytest.mark.parametrize("text, want", [
    ("24 V DC", ["24 V DC"]), ("DC24V", ["24 V DC"]), ("20.4-28.8 VDC", ["24 V DC"]),
    ("100-240 V AC", ["100–240 V AC"]), ("AC 85~264V", ["100–240 V AC"]), ("12 V DC", ["12 V DC"]),
    ("12/24 V DC", ["24 V DC"]), ("AC/DC: 100-240 VAC or 24 VDC", ["100–240 V AC", "24 V DC"]),
])
def test_supply(text, want):
    assert normalize_plc({"supply": text})[0]["supply"] == want


def test_communication():
    out, _ = normalize_plc({"communication": ["PROFINET (RJ45)", "RS485 Modbus RTU", "USB", "Modbus/TCP"]})
    assert set(out["communication"]) == {"PROFINET", "Ethernet", "Modbus RTU", "RS-485", "USB", "Modbus TCP"}
    out, _ = normalize_plc({"communication": ["EtherNet/IP"]})
    assert out["communication"] == ["EtherNet/IP"]  # not also plain Ethernet


@pytest.mark.parametrize("text, khz", [("6 x 100 kHz", 100), ("1 MHz", 1000), ("60kHz (2 ch), 10kHz (4 ch)", 60),
                                       ("fast", None)])
def test_high_speed_counter(text, khz):
    assert frequency_khz(text) == khz


def test_counts_and_series():
    out, _ = normalize_plc({"digital_inputs": 14, "digital_outputs": 10, "analog_inputs": 0, "pulse_axes": -1,
                            "series": " S7-1200 ", "plc_type": "Compact (brick)", "expandable": True})
    assert (out["digital_inputs"], out["digital_outputs"], out["analog_inputs"]) == (14, 10, 0)
    assert out["pulse_axes"] is None and out["series"] == "S7-1200" and out["plc_type"] == "compact"


# ---- the PLC's checks ----

def test_communication_needs_all_ticked():
    c = {"communication": {"value": ["Ethernet", "RS-485"], "required": True}}
    assert check(c, plc(communication=["Ethernet", "RS-485", "USB"]))["met"] == ["Communication"]
    assert check(c, plc())["dropped_for"] == ["Communication: does not meet requirement"]  # no RS-485


def test_brand_is_not_a_requirement():
    """Brand is read off the page and shown, but it is not on the form, in the payload or in the checks."""
    assert "brand" not in PlcCriteria.model_fields and "brand" not in PLC.checks
    assert "brand" not in {f.name for f in PLC.fields}
    assert "brand" in PLC.spec_model.model_fields  # still in results and the CSV
    c = PlcCriteria.model_validate({"brand": {"value": ["Siemens"]}})  # an old client sending it: ignored
    assert "brand" not in c.model_dump()


def test_output_type_any_of():
    c = {"output_type": {"value": ["relay", "transistor (source / PNP)"], "required": True}}
    assert check(c, plc())["met"] == ["Output type"]
    assert check(c, plc(output_type=["transistor (sink / NPN)"]))["dropped_for"] == ["Output type: does not meet requirement"]


def test_io_minimums_and_flexible():
    c = {"min_digital_inputs": {"value": 16, "flexible": True}, "min_digital_outputs": {"value": 10, "required": True}}
    v = check(c, plc(), tolerance=0.2)
    assert v["close_notes"] == ["Digital inputs: 14 DI, close to your 16 DI"] and "Digital outputs" in v["met"]


def test_supply_contains():
    c = {"supply": {"value": "100–240 V AC", "required": True}}
    assert check(c, plc(supply=["100–240 V AC", "24 V DC"]))["met"] == ["Supply"]
    assert check(c, plc())["dropped_for"]


def test_filter_uses_the_plc_checks():
    c = {"min_digital_inputs": {"value": 16, "required": True}, "budget_min": None, "budget_max": None}
    out = nodes.filter_products({"device_type": "plc", "criteria": c,
                                 "products": [plc(title="14di"), plc(title="24di", digital_inputs=24)]})
    assert [p["title"] for p in out["candidates"]] == ["24di"]


# ---- reading pages ----

def test_io_modules_and_hmis_are_the_wrong_kind(monkeypatch):
    llm = FakeLLM([PlcExtraction(is_product_page=True, is_right_device_type=False, title="SM 1221 DI 16 module")])
    monkeypatch.setattr(extractor, "_llm", lambda *a: llm)
    assert real_extract_page("plc", "https://s.test/m", "", "Siemens SM1221 digital input module") == ("wrong_type", None)


def test_a_plc_page_becomes_a_product(monkeypatch):
    raw = PlcExtraction(is_product_page=True, is_right_device_type=True, title="Siemens 6ES7214-1AG40-0XB0",
                        series="S7-1200 CPU 1214C", digital_inputs=14, digital_outputs=10, output_type="Transistor source",
                        analog_inputs=2, supply="24 V DC", communication=["PROFINET (Ethernet)"],
                        high_speed_counter="6 x 100 kHz", pulse_axes=4, expandable=True)
    monkeypatch.setattr(extractor, "_llm", lambda *a: FakeLLM([raw]))
    kind, p = real_extract_page("plc", "https://s.test/1214c", "", "Siemens S7-1200 CPU 1214C PLC 14 DI 10 DO")
    assert kind == "product" and p["brand"] == "Siemens"  # from the title: the model gave no brand
    assert (p["output_type"], p["communication"], p["hsc_khz"]) == (
        ["transistor (source / PNP)"], ["PROFINET", "Ethernet"], 100)


# ---- search wording ----

def test_queries_say_plc_without_a_brand():
    crit = {"currency": "PKR", "plc_type": {"value": "compact", "required": True},
            "min_digital_inputs": {"value": 14, "required": False, "flexible": True}}
    items = query_planner.spec_items(PLC, crit)
    qs = query_planner.fallback_queries(PLC, items, 1, crit)
    assert qs[0] == "PLC compact price in Pakistan" and all("14" not in q for q in qs)
    prompt = query_planner._prompt(PLC, items, crit, 1, [])
    assert "from any maker" in prompt and "expansion modules" in prompt


# ---- a whole search through the API ----

def test_a_plc_search_runs_end_to_end():
    client = TestClient(app)
    devices = {d["key"]: d for d in client.get("/api/devices").json()}
    assert devices["plc"]["enabled"] and not any(not d["enabled"] for d in devices.values())  # nothing "coming soon"

    sid = client.post("/api/searches", json={"device_type": "plc", "criteria": {
        "currency": "PKR", "supply": {"value": "24 V DC", "required": True},
        "communication": {"value": ["Ethernet"], "required": True}}}).json()["id"]
    products = client.get(f"/api/searches/{sid}/results").json()["products"]
    assert products and all("24 V DC" in p["supply"] and "Ethernet" in p["communication"] for p in products)

    rows = list(csv.reader(io.StringIO(client.get(f"/api/searches/{sid}/export.csv").text.lstrip("﻿"))))
    assert {"brand", "series", "digital_inputs", "digital_outputs", "communication", "hsc_khz"} <= set(rows[0])

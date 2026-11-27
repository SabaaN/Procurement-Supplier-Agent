"""The QR code scanner device: criteria, normalisation, its checks, search wording, and a full search."""
import csv
import io

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.devices import get_device
from app.devices.parse import code_size_mil
from app.devices.qr_scanner import QR_CHECKS, QrScannerCriteria, QrScannerExtraction, normalize_qr_scanner
from app.graph import nodes
from app.graph.checks import check_product
from app.main import app
from app.services import extractor, query_planner

from .test_extraction import FakeLLM

real_extract_page = extractor.extract_page  # captured before the autouse fakes replace it
QR = get_device("qr_scanner")


def scanner(**kw):
    base = dict(title="scanner", source_url="https://s.test/p", price=9000, currency="PKR", scanner_type="handheld",
                codes=["QR Code", "Data Matrix", "1D barcodes"], reads_screens=True, interface=["USB"],
                resolution_mil=4.0, reading_distance_mm=300.0, ip_rating=42)
    return {**base, **kw}


def check(criteria, product, **kw):
    return check_product(criteria, product, checks=QR.checks, units=QR.units, **kw)


# ---- criteria and form ----

def test_form_fields_map_to_criteria():
    fields = {f.name for f in QR.fields}
    assert fields <= set(QrScannerCriteria.model_fields) and set(QR_CHECKS) <= fields


def test_criteria_validate():
    c = QrScannerCriteria.model_validate({"scanner_type": {"value": "handheld", "required": True},
                                          "codes": {"value": ["QR Code", "PDF417"]}})
    assert c.codes.value == ["QR Code", "PDF417"]
    with pytest.raises(ValidationError):
        QrScannerCriteria.model_validate({"interface": {"value": ["Firewire"]}})


# ---- normalisation ----

@pytest.mark.parametrize("value, title, want", [
    ("Handheld", "", "handheld"), ("Hand-held gun type", "", "handheld"),
    ("Desktop / hands-free", "", "presentation"), ("Countertop omnidirectional platform", "", "presentation"),
    ("Fixed mount industrial reader", "", "fixed mount"), ("For kiosk and turnstile access control", "", "fixed mount"),
    ("OEM scan engine module", "", "scan engine"), (None, "Embedded QR Code Scanner Module", "scan engine"),
    (None, "USB QR Code Reader", None),  # 'code reader' alone says nothing about the type: not guessed
])
def test_scanner_types(value, title, want):
    assert normalize_qr_scanner({"scanner_type": value, "title": title})[0]["scanner_type"] == want


def test_codes():
    out, _ = normalize_qr_scanner({"codes": ["QR", "DataMatrix", "PDF 417", "Code 128", "EAN-13", "Aztec"]})
    assert set(out["codes"]) == {"QR Code", "Data Matrix", "PDF417", "Aztec", "1D barcodes"}
    out, _ = normalize_qr_scanner({"codes": ["all 2D barcodes"]})
    assert out["codes"] == []  # "2D barcode" is not 1D, and not specifically QR either
    out, _ = normalize_qr_scanner({"codes": None, "title": "2D QR Code Scanner, USB"})
    assert out["codes"] == ["QR Code"]  # a page selling a QR code scanner: it reads QR codes


def test_interfaces():
    out, _ = normalize_qr_scanner({"interface": ["USB-HID", "RS232 (DB9)", "TTL", "Bluetooth 5.0", "2.4G wireless",
                                                 "Wiegand 26/34", "Ethernet TCP/IP", "PROFINET"]})
    assert set(out["interface"]) == {"USB", "RS-232", "TTL / UART", "Bluetooth", "2.4 GHz wireless", "Wiegand",
                                     "Ethernet", "PROFINET"}


@pytest.mark.parametrize("text, mil", [("≥3 mil (1D), 5 mil (2D)", 3), ("4mil", 4), ("Code39 5 mil", 5),
                                       ("high", None), ("0.1 mm", None)])
def test_finest_code(text, mil):
    assert code_size_mil(text) == mil


def test_distance_ip_and_screens():
    out, flags = normalize_qr_scanner({"reading_distance": "0-30 cm", "ip_rating": "IP54", "reads_screens": True})
    assert (out["reading_distance_mm"], out["ip_rating"], out["reads_screens"]) == (300, 54, True) and flags == []


def test_null_lists_from_the_model_are_accepted():
    raw = QrScannerExtraction(is_product_page=False, is_listing_page=True, codes=None, interface=None)
    out, _ = normalize_qr_scanner(raw.model_dump())
    assert out["codes"] == [] and out["interface"] == []


# ---- the scanner's checks ----

def test_codes_need_all_ticked():
    c = {"codes": {"value": ["QR Code", "PDF417"], "required": True}}
    assert check(c, scanner(codes=["QR Code", "PDF417", "1D barcodes"]))["met"] == ["Codes it reads"]
    assert check(c, scanner())["dropped_for"] == ["Codes it reads: does not meet requirement"]


def test_finest_code_is_a_maximum_and_distance_a_minimum():
    c = {"max_resolution_mil": {"value": 5, "required": True}, "min_reading_distance": {"value": 200, "required": True}}
    assert check(c, scanner())["met"] == ["Finest code", "Reading distance"]
    assert len(check(c, scanner(resolution_mil=8.0, reading_distance_mm=100.0))["dropped_for"]) == 2
    flex = {"max_resolution_mil": {"value": 5, "flexible": True}}
    assert check(flex, scanner(resolution_mil=6.0), tolerance=0.2)["close_notes"] == ["Finest code: 6 mil, close to your 5 mil"]


def test_screen_reading_and_interface():
    c = {"reads_screens": {"value": True, "required": True}, "interface": {"value": ["RS-232", "USB"], "required": True}}
    assert check(c, scanner())["met"] == ["Reads phone screens", "Interface"]
    assert check(c, scanner(reads_screens=False))["dropped_for"] == ["Reads phone screens: does not meet requirement"]


def test_filter_uses_the_scanner_checks():
    c = {"scanner_type": {"value": "fixed mount", "required": True}, "budget_min": None, "budget_max": None}
    out = nodes.filter_products({"device_type": "qr_scanner", "criteria": c,
                                 "products": [scanner(title="gun"), scanner(title="fixed", scanner_type="fixed mount")]})
    assert [p["title"] for p in out["candidates"]] == ["fixed"]


# ---- reading pages ----

def test_1d_laser_scanners_and_printers_are_the_wrong_kind(monkeypatch):
    llm = FakeLLM([QrScannerExtraction(is_product_page=True, is_right_device_type=False, title="1D laser scanner")])
    monkeypatch.setattr(extractor, "_llm", lambda *a: llm)
    assert real_extract_page("qr_scanner", "https://s.test/l", "", "1D laser barcode scanner") == ("wrong_type", None)


def test_a_scanner_page_becomes_a_product(monkeypatch):
    raw = QrScannerExtraction(is_product_page=True, is_right_device_type=True, title="Honeywell Voyager 1470g 2D",
                              scanner_type="Handheld", codes=["QR Code", "Data Matrix", "UPC/EAN"],
                              reads_screens=True, interface=["USB", "RS232"], resolution="5 mil",
                              reading_distance="up to 32 cm", ip_rating="IP42")
    monkeypatch.setattr(extractor, "_llm", lambda *a: FakeLLM([raw]))
    kind, p = real_extract_page("qr_scanner", "https://s.test/1470g", "", "Honeywell Voyager 1470g 2D scanner QR")
    assert kind == "product"
    assert (p["scanner_type"], p["codes"], p["interface"]) == ("handheld", ["QR Code", "Data Matrix", "1D barcodes"],
                                                               ["USB", "RS-232"])
    assert (p["resolution_mil"], p["reading_distance_mm"], p["ip_rating"]) == (5, 320, 42)


# ---- search wording ----

def test_queries_say_qr_code_scanner():
    crit = {"currency": "PKR", "scanner_type": {"value": "handheld", "required": True},
            "max_resolution_mil": {"value": 5, "required": False, "flexible": True}}
    items = query_planner.spec_items(QR, crit)
    qs = query_planner.fallback_queries(QR, items, 1, crit)
    assert qs[0] == "QR code scanner handheld price in Pakistan" and all("5 mil" not in q for q in qs)
    prompt = query_planner._prompt(QR, items, crit, 1, [])
    assert "1D-only laser scanners" in prompt


# ---- a whole search through the API ----

def test_a_scanner_search_runs_end_to_end():
    client = TestClient(app)
    devices = {d["key"]: d for d in client.get("/api/devices").json()}
    assert devices["qr_scanner"]["enabled"] and devices["qr_scanner"]["label"] == "QR code scanner"

    sid = client.post("/api/searches", json={"device_type": "qr_scanner", "criteria": {
        "currency": "PKR", "reads_screens": {"value": True, "required": True},
        "interface": {"value": ["USB"], "required": True}}}).json()["id"]
    products = client.get(f"/api/searches/{sid}/results").json()["products"]
    assert products and all(p["reads_screens"] and "USB" in p["interface"] for p in products)

    rows = list(csv.reader(io.StringIO(client.get(f"/api/searches/{sid}/export.csv").text.lstrip("﻿"))))
    assert {"scanner_type", "codes", "reads_screens", "interface", "resolution_mil", "reading_distance_mm"} <= set(rows[0])

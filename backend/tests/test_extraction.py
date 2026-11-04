import pytest

from app.devices.camera import CameraExtraction, normalize_camera
from app.graph import nodes
from app.services import cache, extractor
from app.services.extractor import ExtractionError

# Imported at module load, before the autouse fixture swaps in a fake: this is the real function.
real_extract_product = extractor.extract_product

TEXT = "Acme AC-500 industrial camera. Price: $1,299.00 each. 5 MP, global shutter."


def good_extraction(**kw):
    base = dict(is_product_page=True, title="Acme AC-500", supplier="Acme", price=1299.0,
                currency="USD", moq=1, megapixels=5.0, fps=75.0, shutter="global", interface=["GigE"])
    return CameraExtraction(**{**base, **kw})


class FakeLLM:
    """Stands in for ChatGroq: with_structured_output(...).invoke(...) returns the queued results."""

    def __init__(self, results):
        self.results, self.calls = list(results), 0

    def with_structured_output(self, model):
        return self

    def invoke(self, messages):
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


# ---- normalisation (pure Python) ----

def test_normalize_maps_messy_values_to_canonical_ones():
    fields, flags = normalize_camera({
        "megapixels": 5.0, "fps": 75, "shutter": "Global Shutter", "colour": "Monochrome",
        "scan_type": "Area Scan", "sensor_format": "1/1.8-inch", "lens_mount": "C-mount",
        "interface": ["GigE Vision", "USB 3.0", "RS232"], "bit_depth": 12, "hardware_trigger": True,
    })
    assert fields["shutter"] == "global" and fields["colour"] == "mono" and fields["scan_type"] == "area"
    assert fields["sensor_format"] == '1/1.8"' and fields["lens_mount"] == "C"
    assert fields["interface"] == ["GigE", "USB3"]  # RS232 is not a data interface we track
    assert flags == []


def test_normalize_unknown_values_become_none_and_are_flagged():
    fields, flags = normalize_camera({"shutter": "electronic", "lens_mount": "weird", "megapixels": 9999})
    assert fields["shutter"] is None and fields["lens_mount"] is None and fields["megapixels"] is None
    assert len(flags) == 3


def test_10gige_is_not_confused_with_gige():
    fields, _ = normalize_camera({"interface": ["10GigE", "GigE"]})
    assert fields["interface"] == ["10GigE", "GigE"]


def test_megapixels_computed_in_python_from_width_and_height():
    fields, _ = normalize_camera({"width_px": 2448, "height_px": 2048})
    assert fields["megapixels"] == 5.01


def test_ambiguous_colour_is_not_guessed():
    fields, flags = normalize_camera({"colour": "mono or colour"})
    assert fields["colour"] is None and flags


# ---- extract_product ----

def test_extract_product_builds_a_normalised_product(monkeypatch):
    monkeypatch.setattr(extractor, "_invoke", lambda *a: good_extraction())
    p = real_extract_product("camera", "https://a.test/p", "hit title", TEXT)
    assert p["title"] == "Acme AC-500" and p["price"] == 1299.0 and p["currency"] == "USD"
    assert p["shutter"] == "global" and p["source_url"] == "https://a.test/p" and p["fetched_at"]


def test_price_not_written_on_the_page_is_dropped_and_flagged(monkeypatch):
    monkeypatch.setattr(extractor, "_invoke", lambda *a: good_extraction(price=999.0))
    p = real_extract_product("camera", "https://a.test/p", "", TEXT)
    assert p["price"] is None and p["currency"] is None and "price_not_found_on_page" in p["flags"]


def test_bare_dollar_sign_leaves_currency_unknown(monkeypatch):
    monkeypatch.setattr(extractor, "_invoke", lambda *a: good_extraction(currency="$"))
    p = real_extract_product("camera", "https://a.test/p", "", TEXT)
    assert p["price"] == 1299.0 and p["currency"] is None


def test_non_product_page_returns_none(monkeypatch):
    monkeypatch.setattr(extractor, "_invoke", lambda *a: good_extraction(is_product_page=False))
    assert real_extract_product("camera", "https://a.test/blog", "", TEXT) is None


def test_llm_failure_is_retried_once(monkeypatch):
    llm = FakeLLM([RuntimeError("429 rate limit"), good_extraction()])
    monkeypatch.setattr(extractor, "_llm", lambda: llm)
    monkeypatch.setattr(extractor.time, "sleep", lambda s: None)
    assert real_extract_product("camera", "https://a.test/p", "", TEXT)["title"] == "Acme AC-500"
    assert llm.calls == 2


def test_llm_failing_twice_raises_extraction_error(monkeypatch):
    llm = FakeLLM([RuntimeError("down"), RuntimeError("still down")])
    monkeypatch.setattr(extractor, "_llm", lambda: llm)
    monkeypatch.setattr(extractor.time, "sleep", lambda s: None)
    with pytest.raises(ExtractionError):
        real_extract_product("camera", "https://a.test/p", "", TEXT)
    assert llm.calls == 2


# ---- cache ----

def test_extraction_cache_roundtrip_including_not_a_product():
    assert cache.get_extraction("https://a.test", "camera") is None
    cache.put_extraction("https://a.test", "camera", {"title": "X"})
    cache.put_extraction("https://a.test/blog", "camera", None)
    assert cache.get_extraction("https://a.test", "camera") == {"product": {"title": "X"}}
    assert cache.get_extraction("https://a.test/blog", "camera") == {"product": None}
    assert cache.get_extraction("https://a.test", "camera", max_age_hours=-1) is None  # expired


# ---- the extract node ----

PAGES = [
    {"url": "https://a.test/p", "ok": True, "text": "t", "title": ""},
    {"url": "https://a.test/blog", "ok": True, "text": "t", "title": ""},
]


def test_extract_node_skips_non_product_pages_and_uses_cache(monkeypatch):
    calls = []

    def fake(device_key, url, title, text):
        calls.append(url)
        return None if "blog" in url else {"title": url, "source_url": url, "price": 1.0}

    monkeypatch.setattr(extractor, "extract_product", fake)
    state = {"device_type": "camera", "pages": PAGES}
    out = nodes.extract(state)
    assert [p["source_url"] for p in out["products"]] == ["https://a.test/p"]
    nodes.extract(state)
    assert calls == ["https://a.test/p", "https://a.test/blog"]  # second run: all from the cache


def test_extract_node_errors_when_every_page_fails(monkeypatch):
    def boom(*a):
        raise ExtractionError("rate limited")

    monkeypatch.setattr(extractor, "extract_product", boom)
    out = nodes.extract({"device_type": "camera", "pages": PAGES})
    assert out["products"] == [] and "rate limited" in out["error"]


def test_failed_extractions_are_not_cached(monkeypatch):
    def boom(*a):
        raise ExtractionError("rate limited")

    monkeypatch.setattr(extractor, "extract_product", boom)
    nodes.extract({"device_type": "camera", "pages": PAGES[:1]})
    assert cache.get_extraction("https://a.test/p", "camera") is None


# ---- currency-aware budget filter ----

def test_filter_skips_budget_check_when_currencies_differ():
    state = {
        "criteria": {"budget_max": 20000, "currency": "PKR"},
        "products": [
            {"title": "usd", "price": 450.0, "currency": "USD"},
            {"title": "dear", "price": 30000.0, "currency": "PKR"},
            {"title": "nocur", "price": 15000.0, "currency": None},
        ],
    }
    out = nodes.filter_products(state)
    flags = {p["title"]: p["flags"] for p in out["candidates"]}
    assert list(flags) == ["usd", "nocur"]  # "dear" is over budget in the same currency
    assert any("USD" in f for f in flags["usd"])
    assert "currency_unknown" in flags["nocur"]
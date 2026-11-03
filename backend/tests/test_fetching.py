import dataclasses

import httpx
import pytest

from app.graph import nodes
from app.services import cache, page_fetcher
from app.services.page_fetcher import FetchResult, _bs4_text, clean_html, fetch_page

# Imported at module load, before the autouse fixture swaps page_fetcher.fetch_page for a fake.
# So `fetch_page` here is the real function.

SPEC_LINES = "".join(f"<li>Spec line number {i}: value {i * 7}</li>" for i in range(30))
PAGE = (
    "<html><body><nav>MENU</nav><script>var secret = 1;</script><h1>Cam X</h1>"
    "<table><tr><td>Shutter</td><td>Global</td></tr></table>"
    f"<ul>{SPEC_LINES}</ul><footer>FOOTER</footer></body></html>"
)


@pytest.fixture(autouse=True)
def _clear_robots_cache():
    page_fetcher._ROBOTS.clear()


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


# ---- cleaning ----

def test_bs4_fallback_keeps_table_cells_and_drops_noise():
    text = _bs4_text(PAGE)
    assert "Global" in text
    assert "var secret" not in text and "MENU" not in text and "FOOTER" not in text

def test_clean_html_keeps_spec_table_rows():
    out = clean_html(PAGE)
    assert "Shutter" in out and "Global" in out


def test_clean_html_keeps_definition_lists():
    html = PAGE.replace("<footer>", "<dl><dt>Interface</dt><dd>GigE</dd></dl><footer>")
    out = clean_html(html)
    assert "Interface" in out and "GigE" in out

def test_clean_html_never_returns_script_code():
    assert "var secret" not in clean_html(PAGE)


def test_clean_html_truncates(monkeypatch):
    monkeypatch.setattr(page_fetcher, "settings", dataclasses.replace(page_fetcher.settings, max_page_chars=100))
    assert len(clean_html(PAGE)) <= 100


# ---- fetching (no real network: httpx MockTransport) ----

def test_fetch_ok():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=PAGE)

    r = fetch_page("https://shop.test/cam", client=make_client(handler))
    assert r.ok and "Global" in r.text


def test_fetch_http_error():
    r = fetch_page("https://shop.test/cam", client=make_client(lambda req: httpx.Response(404)))
    assert not r.ok and r.error == "HTTP 404"


def test_fetch_skips_pdf():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4")

    r = fetch_page("https://shop.test/datasheet", client=make_client(handler))
    assert not r.ok and r.error.startswith("PDF")


def test_fetch_flags_pages_with_too_little_text():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html><body><p>hi</p></body></html>")

    r = fetch_page("https://shop.test/spa", client=make_client(handler))
    assert not r.ok and "too little text" in r.error


def test_fetch_respects_robots_txt():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        raise AssertionError("page must not be requested when robots.txt disallows it")

    r = fetch_page("https://shop.test/private/cam", client=make_client(handler))
    assert not r.ok and r.error == "blocked by robots.txt"


def test_fetch_never_raises_on_network_errors():
    def handler(request):
        raise httpx.ConnectError("boom")

    r = fetch_page("https://shop.test/cam", client=make_client(handler))
    assert not r.ok and "ConnectError" in r.error


# ---- cache ----

def test_cache_roundtrip_and_expiry():
    assert cache.get_page("https://a.test") is None
    cache.put_page("https://a.test", True, "hello", None)
    assert cache.get_page("https://a.test") == {"url": "https://a.test", "ok": True, "text": "hello", "error": None}
    assert cache.get_page("https://a.test", max_age_hours=-1) is None  # expired


# ---- the fetch_clean node ----

def test_fetch_clean_uses_cache_and_skips_pages_already_tried(monkeypatch):
    calls = []

    def fake_fetch(url, client=None):
        calls.append(url)
        return FetchResult(url, True, text="x" * 300)

    monkeypatch.setattr(page_fetcher, "fetch_page", fake_fetch)
    cache.put_page("https://c.test", True, "cached text", None)
    state = {
        "urls": ["https://a.test", "https://c.test"],
        "hits": [{"url": "https://a.test", "title": "A"}],
        "pages": [],
    }
    out = nodes.fetch_clean(state)
    assert calls == ["https://a.test"]  # c.test came from the cache
    by_url = {p["url"]: p for p in out["pages"]}
    assert by_url["https://c.test"]["text"] == "cached text"
    assert by_url["https://a.test"]["title"] == "A"

    again = nodes.fetch_clean({**state, "pages": out["pages"]})
    assert calls == ["https://a.test"] and len(again["pages"]) == 2  # nothing new to fetch


def test_fetch_clean_caps_pages_per_attempt(monkeypatch):
    monkeypatch.setattr(nodes, "settings", dataclasses.replace(nodes.settings, max_pages_per_attempt=2))
    state = {"urls": [f"https://x.test/{i}" for i in range(5)], "pages": []}
    first = nodes.fetch_clean(state)
    assert len(first["pages"]) == 2
    second = nodes.fetch_clean({**state, "pages": first["pages"]})
    assert len(second["pages"]) == 4  # the next attempt picks up where this one stopped


def test_failed_pages_are_cached_but_timeouts_are_not(monkeypatch):
    calls = []

    def fake_fetch(url, client=None):
        calls.append(url)
        error = "timeout" if "slow" in url else "HTTP 403"
        return FetchResult(url, False, error=error)

    monkeypatch.setattr(page_fetcher, "fetch_page", fake_fetch)
    state = {"urls": ["https://blocked.test", "https://slow.test"], "pages": []}
    first = nodes.fetch_clean(state)
    assert all(not p["ok"] for p in first["pages"])

    nodes.fetch_clean(state)  # fresh state again: the same two URLs
    assert calls.count("https://blocked.test") == 1  # remembered
    assert calls.count("https://slow.test") == 2  # tried again


def test_extract_stub_ignores_failed_pages():
    state = {
        "device_type": "camera",
        "pages": [{"url": "https://bad.test", "ok": False, "text": "", "error": "HTTP 403"}],
    }
    assert nodes.extract(state)["products"] == []
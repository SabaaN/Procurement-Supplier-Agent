"""Supplier contacts, datasheet links, the datasheet download and the new CSV columns."""
import csv
import io

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import contacts, datasheets, page_fetcher, store
from app.services.contacts import enrich, page_links
from app.services.datasheets import DatasheetError, download, filename_for
from .conftest import PRODUCT_TEXT

real_fetch_page = page_fetcher.fetch_page  # before the autouse fixture swaps in a fake

SHOP = """
<html><head><meta property="og:site_name" content="Vision Tech Karachi"></head><body>
<h1>Acme AC-500 camera</h1>
<p>Questions? Call us: +92 21 3456 7890 or write to sales@visiontech.pk.</p>
<a href="/files/AC-500_Datasheet.pdf">Download datasheet</a>
<a href="/files/AC-500-manual.pdf">User manual</a>
<a href="/brochure.pdf">Company brochure</a>
<a href="#specs">Specifications</a>
<a href="mailto:info@acme-global.com?subject=Hi">Manufacturer</a>
<footer><a href="tel:+92-300-1234567">WhatsApp</a> noreply@sentry.io logo@2x.png</footer>
</body></html>
"""


# ---- reading links from HTML ----

def test_page_links_finds_datasheet_contacts_and_site_name():
    links = page_links(SHOP, "https://www.visiontech.pk/p/ac-500")
    assert links["datasheets"][0] == "https://www.visiontech.pk/files/AC-500_Datasheet.pdf"
    assert "https://www.visiontech.pk/brochure.pdf" in links["datasheets"]  # weaker match, ranked lower
    assert not any("manual" in u for u in links["datasheets"])
    assert not any("#" in u for u in links["datasheets"])
    assert links["emails"][0] == "sales@visiontech.pk"  # the supplier's own domain comes first
    assert "info@acme-global.com" in links["emails"]
    assert not any("sentry" in e or e.endswith(".png") for e in links["emails"])
    assert links["phones"][0] == "+92-300-1234567"  # tel: links come first
    assert "+92 21 3456 7890" in links["phones"]
    assert links["site_name"] == "Vision Tech Karachi"


def test_page_links_ignores_numbers_without_a_phone_label():
    links = page_links("<p>Part 1234567890. Price 125000. Order 2023-11-10-55.</p>", "https://a.test/")
    assert links["phones"] == [] and links["emails"] == [] and links["datasheets"] == []


def test_non_pdf_link_counts_only_when_it_says_datasheet():
    html = '<a href="/download?id=7">Datasheet</a><a href="/specs">Full specifications</a>'
    assert page_links(html, "https://a.test/p")["datasheets"] == ["https://a.test/download?id=7"]


def test_enrich_falls_back_to_supplier_then_hostname():
    p = {"source_url": "https://www.shop.test/x", "supplier": "Acme"}
    assert enrich(p, {})["company_name"] == "Acme"
    assert enrich({"source_url": "https://www.shop.test/x"}, None)["company_name"] == "shop.test"
    out = enrich(p, page_links(SHOP, "https://www.visiontech.pk/p"))
    assert out["company_name"] == "Vision Tech Karachi" and out["email"] == "sales@visiontech.pk"
    assert out["product_link"] == "https://www.shop.test/x" and out["datasheet_url"].endswith("_Datasheet.pdf")


def test_fetch_page_returns_links():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "text/html"}, text=SHOP + "<p>" + "spec " * 100 + "</p>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    r = real_fetch_page("https://www.visiontech.pk/p/ac-500", client=client)
    assert r.ok and r.links["emails"][0] == "sales@visiontech.pk"


# ---- through the whole search ----

LINKS = {
    "datasheets": ["https://maker.test/ds.pdf"], "emails": ["sales@shop.test"],
    "phones": ["+92 300 1234567"], "site_name": "Shop Test",
}


@pytest.fixture
def api(monkeypatch):
    def fake_fetch(url, client=None):
        return page_fetcher.FetchResult(url, True, text=PRODUCT_TEXT, links=LINKS)

    monkeypatch.setattr(page_fetcher, "fetch_page", fake_fetch)
    monkeypatch.setattr(datasheets, "_resolve", lambda host: ["93.184.216.34"])  # a public address
    return TestClient(app)


def run_search(api):
    sid = api.post("/api/searches", json={"device_type": "camera", "criteria": {}}).json()["id"]
    return sid, api.get(f"/api/searches/{sid}/results").json()["products"]


def test_products_carry_contacts_and_csv_exports_them(api):
    sid, products = run_search(api)
    p = products[0]
    assert (p["company_name"], p["email"], p["contact_no"]) == ("Shop Test", "sales@shop.test", "+92 300 1234567")
    assert p["product_link"] == p["source_url"] and p["datasheet_url"] == "https://maker.test/ds.pdf"

    rows = list(csv.reader(io.StringIO(api.get(f"/api/searches/{sid}/export.csv").text.lstrip("﻿"))))
    header, first = rows[0], dict(zip(rows[0], rows[1]))
    for col in ("Company name", "Email", "Contact no", "Product link", "Datasheet (PDF)"):
        assert col in header
    assert first["Email"] == "sales@shop.test" and first["Contact no"] == "'+92 300 1234567"  # guarded: Excel would read a bare + as a formula
    assert first["Product link"] == p["source_url"] and first["Datasheet (PDF)"] == "https://maker.test/ds.pdf"


def test_csv_fills_contact_columns_for_products_saved_before_them(api):
    sid = store.create_search("camera", {})
    store.save_products(sid, [{"title": "Old", "source_url": "https://old.test/p", "supplier": "Old Co"}])
    rows = list(csv.reader(io.StringIO(api.get(f"/api/searches/{sid}/export.csv").text.lstrip("﻿"))))
    first = dict(zip(rows[0], rows[1]))
    assert first["Company name"] == "Old Co" and first["Product link"] == "https://old.test/p"


def test_datasheet_endpoint_returns_the_pdf_as_a_download(api, monkeypatch):
    monkeypatch.setattr(datasheets, "download", lambda url: b"%PDF-1.7 fake")
    sid, products = run_search(api)
    r = api.get(f"/api/searches/{sid}/products/{products[0]['id']}/datasheet")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert r.headers["content-type"] == "application/pdf"
    assert 'attachment; filename="ds.pdf"' == r.headers["content-disposition"]


def test_datasheet_endpoint_errors(api, monkeypatch):
    sid, products = run_search(api)
    pid = products[0]["id"]
    assert api.get(f"/api/searches/{sid}/products/999999/datasheet").status_code == 404

    def broken(url):
        raise DatasheetError("Supplier site answered HTTP 404")

    monkeypatch.setattr(datasheets, "download", broken)
    r = api.get(f"/api/searches/{sid}/products/{pid}/datasheet")
    assert r.status_code == 502 and "HTTP 404" in r.json()["detail"]

    plain = store.create_search("camera", {})
    store.save_products(plain, [{"title": "No sheet", "source_url": "https://a.test"}])
    other = store.get_products(plain)[0]["id"]
    assert api.get(f"/api/searches/{plain}/products/{other}/datasheet").status_code == 404


# ---- downloading safely ----

def mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_download_follows_redirects_and_checks_it_is_a_pdf(monkeypatch):
    monkeypatch.setattr(datasheets, "_resolve", lambda host: ["93.184.216.34"])

    def handler(request):
        if request.url.path == "/go":
            return httpx.Response(302, headers={"location": "/real.pdf"})
        if request.url.path == "/real.pdf":
            return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=b"%PDF-1.4 x")
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html>login</html>")

    assert download("https://s.test/go", client=mock(handler)) == b"%PDF-1.4 x"
    with pytest.raises(DatasheetError, match="web page"):
        download("https://s.test/page", client=mock(handler))


def test_download_rejects_non_pdf_and_private_addresses(monkeypatch):
    monkeypatch.setattr(datasheets, "_resolve", lambda host: ["93.184.216.34"])
    fake = mock(lambda r: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"PK zip"))
    with pytest.raises(DatasheetError, match="not a PDF"):
        download("https://s.test/a.pdf", client=fake)

    monkeypatch.setattr(datasheets, "_resolve", lambda host: ["127.0.0.1"])
    with pytest.raises(DatasheetError, match="private"):
        download("http://localhost:8000/a.pdf", client=fake)

    # a public page that redirects to an internal address is stopped at the redirect
    def resolve(host):
        return ["10.0.0.5"] if host == "internal.test" else ["93.184.216.34"]

    monkeypatch.setattr(datasheets, "_resolve", resolve)
    hop = mock(lambda r: httpx.Response(302, headers={"location": "http://internal.test/x.pdf"}))
    with pytest.raises(DatasheetError, match="private"):
        download("https://s.test/a.pdf", client=hop)
    with pytest.raises(DatasheetError, match="web address"):
        download("file:///etc/passwd", client=hop)


def test_filename_is_safe():
    assert filename_for("https://a.test/x/AC 500 (rev2).pdf", "t") == "AC-500-rev2.pdf"
    assert filename_for("https://a.test/download?id=7", 'Cam "X" / 5MP') == "Cam-X-5MP-datasheet.pdf"
    assert filename_for("https://a.test/", None) == "product-datasheet.pdf"

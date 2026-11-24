"""Prices read from the raw HTML, because the page cleaner drops the boxes they sit in."""
from app.graph import nodes
from app.services import cache, extractor, page_fetcher
from app.services.page_fetcher import clean_html
from app.services.prices import page_prices, price_block

from .test_extraction import FakeLLM
from app.devices.camera import CameraExtraction

# Shaped like a made-in-china.com product page: price tiers in a box beside the gallery,
# the long description in <article>, and schema.org product data in JSON-LD.
MIC = """<html><head>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"RV1126 IP Camera Module",
 "offers":{"@type":"AggregateOffer","lowPrice":"180.0","highPrice":"200.0","priceCurrency":"USD"}}</script>
</head><body>
<header><nav>Home | Products | Contact</nav></header>
<div class="pro-info">
  <h1>Rolling Shutter Ethernet 1080P 30fps Rockchip RV1126 IP Camera Module</h1>
  <div class="sr-proMainInfo-baseInfo-propertyPrice">
    <div class="swiper-money-container"><span class="price">US$200.00</span> <span class="unit">1-99 Pieces</span></div>
    <div class="swiper-money-container"><span class="price">US$180.00</span> <span class="unit">100+ Pieces</span></div>
  </div>
  <button>Contact Supplier</button>
</div>
<article>
<h2>Product Description</h2>
""" + "<p>This 2MP IP camera module uses the Rockchip RV1126 processor with a rolling shutter sensor, delivering 1080P at 30fps over Ethernet. It supports H.265 encoding and is suited to smart cameras and access control.</p>" * 6 + """
<table><tr><td>Resolution</td><td>1920x1080</td></tr><tr><td>Frame rate</td><td>30fps</td></tr></table>
</article>
<div class="related-products"><span class="price-range">US$15.00</span></div>
<footer>Copyright</footer>
</body></html>"""


def test_the_cleaner_drops_the_price_box():
    """The cause: the cleaned text the model reads has the specs but not the price."""
    text = clean_html(MIC)
    assert "Rockchip RV1126" in text and "US$200.00" not in text


def test_visible_price_tiers_and_embedded_offer_are_found():
    p = page_prices(MIC)
    assert p["shown"] == ["US$200.00 1-99 Pieces US$180.00 100+ Pieces"]  # the whole box, tiers together
    assert p["data"] == ["180.0 - 200.0 USD"]
    assert not any("15.00" in s for s in p["shown"])  # a related product's price is not this one's


def test_the_model_sees_the_prices_and_the_guard_accepts_them(monkeypatch):
    seen = {}

    class Reader(FakeLLM):
        def invoke(self, messages):
            seen["text"] = messages[-1][1]
            return super().invoke(messages)

    raw = CameraExtraction(is_product_page=True, is_right_device_type=True, title="RV1126 IP Camera Module",
                           price=200.0, currency="USD", moq=1)
    monkeypatch.setattr(extractor, "_llm", lambda *a: Reader([raw]))
    monkeypatch.setattr(extractor, "extract_page", REAL_EXTRACT_PAGE)
    url = "https://smartgiant.en.made-in-china.com/product/x.html"
    page = {"url": url, "ok": True, "title": "", "text": clean_html(MIC),
            "links": {"prices": page_prices(MIC)}}
    results, *_ = nodes._extract_pages("camera", [page])
    product = results[0][2]
    assert "Prices shown on the page:\n- US$200.00 1-99 Pieces" in seen["text"]
    assert (product["price"], product["currency"]) == (200.0, "USD")  # kept: the number is on the page now
    assert "price_not_found_on_page" not in product["flags"]


def test_a_price_still_has_to_be_on_the_page():
    raw = CameraExtraction(is_product_page=True, title="X", price=999.0, currency="USD")
    product = extractor._build_product(extractor.get_device("camera"), raw, "https://a.test", "",
                                       clean_html(MIC) + price_block(page_prices(MIC)))
    assert product["price"] is None and "price_not_found_on_page" in product["flags"]


def test_shop_platform_markup():
    shopify = ('<meta property="product:price:amount" content="45,500.00">'
               '<meta property="product:price:currency" content="PKR">'
               '<div class="product__price"><span class="price-item price-item--sale">Rs.45,500.00</span></div>')
    p = page_prices(shopify)
    assert p["data"] == ["45,500.00 PKR"] and p["shown"] == ["Rs.45,500.00"]

    woo = ('<p class="price"><del><span class="amount">Rs 9,000</span></del> '
           '<ins><span class="amount">Rs 7,500</span></ins></p>'
           '<span itemprop="price" content="7500">7,500</span><meta itemprop="priceCurrency" content="PKR">')
    p = page_prices(woo)
    assert p["shown"][0] == "Rs 7,500" and not any("9,000" in s for s in p["shown"])  # sale price, not the old one
    assert "7500 PKR" in p["data"]


def test_bold_or_unrelated_classes_are_not_mistaken():
    html = ('<div class="price bold">PKR 12,000</div><div class="price-filter">0 - 50000</div>'
            '<div class="sort-by-price">Low to high 1</div>')
    assert page_prices(html)["shown"] == ["PKR 12,000"]


def test_pages_without_prices_add_nothing():
    assert page_prices("<p>Contact us for a quote</p>") == {"shown": [], "data": [], "count": 0, "products": 0}
    assert price_block({"shown": [], "data": []}) == "" and price_block(None) == ""


def test_us_dollar_sign_is_read_as_usd():
    assert extractor._currency("US$") == "USD" and extractor._currency("$") is None  # bare $ stays unknown


def test_pages_cached_before_prices_were_collected_are_read_again():
    cache.put_page("https://old.test", True, "text", None, {"emails": ["a@b.pk"]})
    assert cache.get_page("https://old.test") is None
    cache.put_page("https://new.test", True, "text", None, {"emails": [], "prices": {"shown": [], "data": []}})
    assert cache.get_page("https://new.test")["links"]["prices"] == {"shown": [], "data": []}


def test_fetch_page_collects_prices():
    import httpx

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "text/html"}, text=MIC)

    r = REAL_FETCH("https://smartgiant.test/p", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert r.ok and r.links["prices"]["shown"][0].startswith("US$200.00 1-99 Pieces")


REAL_EXTRACT_PAGE = extractor.extract_page  # captured at import, before the autouse fakes replace them
REAL_FETCH = page_fetcher.fetch_page

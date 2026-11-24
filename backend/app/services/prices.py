"""Prices read from a page's raw HTML, in Python.

The page cleaner keeps the main description and drops the boxes around it as clutter, and on many
shops (made-in-china.com, Shopify, WooCommerce...) the price sits in exactly such a box. So prices
are collected here from the HTML itself and added to the text the model reads:

- visible price elements: anything the shop marks as a price (class or id containing "price",
  itemprop="price"), e.g. "US$200.00 1-99 Pieces";
- the product data shops embed for search engines: schema.org offers (JSON-LD or microdata)
  and price meta tags, e.g. 180.0 USD.

The model still picks the single-unit price, and the extractor still keeps it only if that number
is written in the text it was given.
"""
import json
import re

from bs4 import BeautifulSoup

MAX_SHOWN = 6  # visible price snippets kept per page
MAX_LEN = 140  # longer than this is a whole section, not a price
_DIGIT = re.compile(r"\d")
_PRICE_ATTR = re.compile(r"price", re.I)
# price-like class names that are not this product's price
_NOT_PRICE = re.compile(
    r"(^|[-_\s])(filter|slider|range|compare|related|recommend|similar|sort|old|was|regular|crossed|strike)([-_\s]|$)",
    re.I,
)


def _offers(node, out: list[str]):
    """schema.org offers found anywhere in a JSON-LD structure: '200.00 USD', '180 - 200 USD'."""
    if isinstance(node, list):
        for item in node:
            _offers(item, out)
        return
    if not isinstance(node, dict):
        return
    kinds = node.get("@type")
    kinds = kinds if isinstance(kinds, list) else [kinds]
    if any(k in ("Offer", "AggregateOffer") for k in kinds):
        cur = node.get("priceCurrency") or ""
        if node.get("price") not in (None, ""):
            out.append(f"{node['price']} {cur}".strip())
        elif node.get("lowPrice") not in (None, ""):
            high = node.get("highPrice")
            out.append(f"{node['lowPrice']}{f' - {high}' if high not in (None, '') else ''} {cur}".strip())
    for value in node.values():
        if isinstance(value, (dict, list)):
            _offers(value, out)


def _count_products(node) -> int:
    """How many schema.org Products a JSON-LD structure describes (an ItemList counts its items)."""
    if isinstance(node, list):
        return sum(_count_products(item) for item in node)
    if not isinstance(node, dict):
        return 0
    kinds = node.get("@type")
    kinds = kinds if isinstance(kinds, list) else [kinds]
    if "ItemList" in kinds and isinstance(node.get("itemListElement"), list):
        return len(node["itemListElement"])
    own = 1 if "Product" in kinds else 0
    return own + sum(_count_products(v) for k, v in node.items() if k != "offers" and isinstance(v, (dict, list)))


def products_in_data(soup) -> int:
    """Products described in the page's embedded data: 1 on a product page, many on a listing, 0 if none."""
    total = 0
    for tag in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        try:
            total += _count_products(json.loads(tag.string or tag.get_text() or ""))
        except (ValueError, TypeError):
            continue
    total += len(soup.find_all(attrs={"itemtype": re.compile(r"schema\.org/Product$", re.I)}))
    return total


def _structured(soup) -> list[str]:
    out: list[str] = []
    for tag in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        try:
            _offers(json.loads(tag.string or tag.get_text() or ""), out)
        except (ValueError, TypeError):
            continue
    for prop in ("product:price:amount", "og:price:amount"):
        meta = soup.find("meta", attrs={"property": prop})
        if meta and (meta.get("content") or "").strip():
            cur = soup.find("meta", attrs={"property": prop.replace("amount", "currency")})
            out.append(f"{meta['content'].strip()} {(cur.get('content') or '').strip() if cur else ''}".strip())
    for tag in soup.find_all(attrs={"itemprop": "price"}):
        value = (tag.get("content") or tag.get_text(" ", strip=True) or "").strip()
        if value and _DIGIT.search(value):
            cur = tag.find_next(attrs={"itemprop": "priceCurrency"})
            out.append(f"{value} {(cur.get('content') or cur.get_text(strip=True)) if cur else ''}".strip())
    return list(dict.fromkeys(out))[:MAX_SHOWN]


def _visible(soup) -> list[str]:
    candidates = []
    for tag in soup.find_all(True):
        attrs = " ".join(tag.get("class") or []) + " " + (tag.get("id") or "") + " " + (tag.get("itemprop") or "")
        if not _PRICE_ATTR.search(attrs) or _NOT_PRICE.search(attrs):
            continue
        text = " ".join(tag.get_text(" ", strip=True).split())
        if 2 <= len(text) <= MAX_LEN and _DIGIT.search(text):
            candidates.append(text)
    candidates = list(dict.fromkeys(candidates))
    # a price box and the spans inside it both match: keep the box, which has the tiers together
    return [c for c in candidates if not any(c != other and c in other for other in candidates)]


def page_prices(html: str) -> dict:
    """From raw HTML: {'shown': visible price texts, 'data': embedded offers,
    'count': how many separate prices are shown, 'products': products in the embedded data}.
    count and products help tell a shop listing from a single product page without the model."""
    soup = BeautifulSoup(html, "html.parser")
    data = _structured(soup)  # before scripts are removed: JSON-LD lives in <script>
    products = products_in_data(soup)
    # crossed-out pre-sale prices (<del>Rs 9,000</del> <ins>Rs 7,500</ins>) are not the price
    for tag in soup(["script", "style", "noscript", "svg", "template", "del", "s", "strike"]):
        tag.decompose()
    shown = _visible(soup)
    return {"shown": shown[:MAX_SHOWN], "data": data, "count": len(shown), "products": products}


def price_block(prices: dict | None) -> str:
    """The text added after a page for the model, or "" when the page had no prices found."""
    prices = prices or {}
    lines = [f"- {p}" for p in prices.get("shown", [])]
    lines += [f"- {p} (from the page's product data)" for p in prices.get("data", [])]
    return "\n\nPrices shown on the page:\n" + "\n".join(lines) if lines else ""
"""Decide, without the model, whether a page is obviously not worth a model call. Pure Python.

Every page the model reads costs Groq tokens, and most pages a search turns up are not product
pages. Three cases are clear from the page itself:

- 'not_product': its address is a blog post, news item, guide, company or policy page; or it never
  mentions the device and shows no price.
- 'listing': a shop category or search page, i.e. many product links and many prices, and its
  embedded data does not describe exactly one product. Its product links are followed directly.

Anything else goes to the model as before. The rules are deliberately cautious: when unsure, read it.
"""
import re
from urllib.parse import urlsplit

from . import pakistan

# whole path segments that are never a product page
_NOT_PRODUCT_PATH = re.compile(
    r"/(blog|blogs|news|article|articles|post|posts|forum|forums|wiki|tag|tags|author|press|careers|jobs|"
    r"about|about-us|contact|contact-us|faq|faqs|privacy|privacy-policy|terms|terms-and-conditions|"
    r"knowledge|knowledgebase|kb|tutorial|tutorials|guide|guides|learn|resources|events|webinar|webinars)(/|$)",
    re.I,
)
# a currency next to a number in the page text: "Rs 4,500", "PKR 4500", "US$ 38", "4500 PKR"
_PRICE_IN_TEXT = re.compile(
    r"(\brs\.?|\bpkr|\busd|us\$|\$|€|£|₹|\baed|\beur)\s?\d|\d\s?(pkr|usd|rs\b|aed|eur)", re.I
)

LISTING_MIN_LINKS = 8  # product links on the page
LISTING_MIN_PRICES = 4  # separate prices shown


def triage(device, page: dict, pakistan_only: bool = False) -> str | None:
    """'not_product', 'not_pakistan', 'listing', or None (send it to the model)."""
    path = urlsplit(page.get("url", "")).path
    if _NOT_PRODUCT_PATH.search(path):
        return "not_product"
    if pakistan_only and not pakistan.page_evidence(page):
        return "not_pakistan"  # the buyer only wants sellers in Pakistan, and this page shows no sign of it

    links = page.get("links") or {}
    prices = links.get("prices") or {}
    text = f"{page.get('title', '')} {page.get('text', '')}".lower()

    has_price = bool(prices.get("shown") or prices.get("data") or _PRICE_IN_TEXT.search(text))
    if device.page_words and not has_price and not any(w in text for w in device.page_words):
        return "not_product"

    # pages cached before prices were counted have no 'count': never shortcut those
    if (len(links.get("products") or []) >= LISTING_MIN_LINKS
            and (prices.get("count") or 0) >= LISTING_MIN_PRICES
            and prices.get("products") != 1):
        return "listing"
    return None

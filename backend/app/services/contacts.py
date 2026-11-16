"""Supplier contact details and datasheet links, read from a page's raw HTML.

The cleaned page text drops links and footers, which is exactly where emails, phone numbers
and "Download datasheet (PDF)" links live. So these are found in Python from the HTML itself,
never by the model: a contact detail is either written on the page or it stays empty.
"""
import re
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

MAX_LINKS = 5  # per kind, per page
MAX_PRODUCT_LINKS = 30  # candidate product links kept from one listing page

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_JUNK_EMAIL = re.compile(
    r"\.(png|jpe?g|gif|webp|svg)$|@(example\.|sentry|wixpress|domain\.)|^(user|name|email|you)@", re.I
)
# A phone is only taken from text when a label is right before it ("Tel: ...", "Call us ...").
_PHONE_LABEL = re.compile(
    r"(?:phone|tel|telephone|call(?:\s+us)?|mobile|mob|cell|whats\s?app|contact(?:\s+no)?|ph)\b\.?\s*(?:no\.?|number|#)?\s*[:\-]?\s*"
    r"(\+?\(?\d[\d\s().\-]{6,}\d)",
    re.I,
)
_DATASHEET_WORDS = ("datasheet", "data sheet", "data-sheet", "data_sheet", "spec sheet", "specsheet", "spec-sheet")
_WEAK_WORDS = ("brochure", "catalog", "catalogue", "product sheet", "flyer", "technical")
_NOT_DATASHEET = ("manual", "terms", "privacy", "warranty", "invoice", "policy", "certificate", "declaration")


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _clean_phone(raw: str) -> str | None:
    """Tidy a phone number, or None if it doesn't have a plausible number of digits."""
    raw = unquote(raw).strip()
    digits = re.sub(r"\D", "", raw)
    if not 8 <= len(digits) <= 15:
        return None
    text = re.sub(r"\s+", " ", re.sub(r"[^\d+()\-.\s]", "", raw)).strip(" .-")
    return text or None


def _datasheet_score(href: str, text: str) -> int:
    """How much a link looks like a product datasheet. 0 = not a datasheet."""
    path = urlsplit(href).path.lower()
    blob = f"{text} {unquote(path)}".lower()
    is_pdf = path.endswith(".pdf")
    if any(w in blob for w in _NOT_DATASHEET):
        return 0
    strong = any(w in blob for w in _DATASHEET_WORDS)
    if is_pdf:
        return 2 + (3 if strong else 2 if "specification" in blob else 1 if any(w in blob for w in _WEAK_WORDS) else 0)
    # a link that isn't a .pdf counts only when it clearly says "datasheet" (e.g. /download?id=123)
    return 1 if strong else 0


# Paths that look like one product, on common shop platforms (WooCommerce, Shopify, Magento, Daraz...).
_PRODUCT_PATH = re.compile(
    r"/(product|products|p|item|items|dp|goods|shop/[^/]+)/[^/?#]+|-i\d{5,}(-s\d+)?\.html|/\d{4,}[-/][a-z0-9-]{6,}|\.html?$",
    re.I,
)
_NOT_PRODUCT_PATH = re.compile(
    r"/(cart|checkout|account|my-account|login|register|signin|wishlist|compare|category|categories|tag|tags|"
    r"blog|news|page|search|brand|brands|contact|about|policy|privacy|terms|faq|help|support|download|downloads)"
    r"([-_./?]|$)|[?&](page|sort|order|filter|orderby|add-to-cart)=|\.(pdf|jpe?g|png|gif|webp|zip)$",
    re.I,
)


def _product_links(soup, page_url: str) -> list[str]:
    """Same-site links that look like individual product pages, in page order (shop order)."""
    host = _host(page_url)
    page = page_url.split("#")[0].rstrip("/")
    out = []
    for a in soup.find_all("a", href=True):
        full = urljoin(page_url, a["href"].strip()).split("#")[0]
        parts = urlsplit(full)
        if parts.scheme not in ("http", "https") or full.rstrip("/") == page or full in out:
            continue
        link_host = parts.netloc.lower().removeprefix("www.")
        if not (link_host == host or link_host.endswith("." + host) or host.endswith("." + link_host)):
            continue
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        text = a.get_text(" ", strip=True) or a.get("title") or ""
        if _NOT_PRODUCT_PATH.search(path) or not _PRODUCT_PATH.search(path) or len(text) < 4:
            continue
        out.append(full)
        if len(out) >= MAX_PRODUCT_LINKS:
            break
    return out


def page_links(html: str, page_url: str) -> dict:
    """{'datasheets', 'emails', 'phones', 'products': [...], 'site_name': str | None} from raw HTML.
    'products' are links to single product pages, used when the page turns out to be a listing."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):  # footers and navs stay: contacts live there
        tag.decompose()

    datasheets: dict[str, int] = {}
    emails: list[str] = []
    phones: list[str] = []

    def add_email(value: str):
        value = unquote(value).split("?")[0].strip().strip(".").lower()
        if _EMAIL.fullmatch(value) and not _JUNK_EMAIL.search(value) and value not in emails:
            emails.append(value)

    def add_phone(value: str):
        phone = _clean_phone(value)
        if phone and re.sub(r"\D", "", phone) not in {re.sub(r"\D", "", p) for p in phones}:
            phones.append(phone)

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        low = href.lower()
        if low.startswith("mailto:"):
            for part in href[7:].split(","):
                add_email(part)
        elif low.startswith("tel:"):
            add_phone(href[4:])
        elif not low.startswith("#") and not re.match(r"^[a-z][a-z0-9+.\-]*:", low) or low.startswith(("http://", "https://")):
            full = urljoin(page_url, href).split("#")[0]
            if not full.lower().startswith(("http://", "https://")):
                continue
            label = " ".join(filter(None, [a.get_text(" ", strip=True), a.get("title"), a.get("aria-label")]))
            score = _datasheet_score(full, label)
            if score:
                datasheets[full] = max(score, datasheets.get(full, 0))

    text = soup.get_text("\n")
    for match in _EMAIL.findall(text):
        add_email(match)
    for match in _PHONE_LABEL.findall(text):
        add_phone(match)

    # The supplier's own address first: shops often also show a manufacturer's or a platform's.
    host = _host(page_url)
    emails.sort(key=lambda e: not (host and (host.endswith(e.split("@")[1]) or e.split("@")[1].endswith(host))))

    site_name = None
    for attrs in ({"property": "og:site_name"}, {"name": "application-name"}):
        meta = soup.find("meta", attrs=attrs)
        if meta and (meta.get("content") or "").strip():
            site_name = meta["content"].strip()[:120]
            break

    ranked = sorted(datasheets, key=lambda u: -datasheets[u])  # stable: page order breaks ties
    return {
        "datasheets": ranked[:MAX_LINKS],
        "emails": emails[:MAX_LINKS],
        "phones": phones[:MAX_LINKS],
        "products": _product_links(soup, page_url),
        "site_name": site_name,
    }


def enrich(product: dict, links: dict | None) -> dict:
    """Add company name, email, contact number, product link and datasheet to one product."""
    links = links or {}
    url = product.get("source_url") or ""
    return {
        **product,
        "company_name": links.get("site_name") or product.get("supplier") or _host(url) or None,
        "email": next(iter(links.get("emails") or []), None),
        "contact_no": next(iter(links.get("phones") or []), None),
        "product_link": url or None,
        "datasheet_url": next(iter(links.get("datasheets") or []), None),
    }

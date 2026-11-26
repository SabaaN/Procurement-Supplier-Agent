"""Is this seller in Pakistan? Evidence read from the page in Python, never guessed by the model.

Used when the buyer ticks "Pakistan market only". A seller counts as Pakistani when the page shows at
least one of:

- a .pk website (shop.pk, company.com.pk);
- a Pakistani phone number (+92 / 0092 / 03xx-xxxxxxx);
- a price in PKR, or in "Rs" on a page with no sign of India (₹, INR, +91, a .in website);
- an address in a Pakistani city.

A page that only says "we ship to Pakistan" does not count.
"""
import re
from urllib.parse import urlsplit

_PK_PHONE = re.compile(r"(?:\+|\b00)\s?92[\s.-]?\(?\d|\b03\d{2}[\s.-]?\d{7}\b")
_PKR = re.compile(r"\bpkr\b|\bpak(?:istani)?\s?rupees?\b", re.I)
_RS = re.compile(r"\brs\.?\s?\d", re.I)
_INDIA = re.compile(r"₹|\binr\b|(?:\+|\b00)\s?91[\s.-]?\d", re.I)
_CITIES = ("karachi", "lahore", "islamabad", "rawalpindi", "faisalabad", "multan", "peshawar", "quetta",
           "sialkot", "gujranwala")
_CITY = re.compile(rf"\b({'|'.join(_CITIES)})\b", re.I)


def _host(url: str) -> str:
    return urlsplit(url or "").netloc.lower().split(":")[0]


def evidence(url: str, text: str, links: dict | None = None, currency: str | None = None) -> list[str]:
    """Reasons to believe the seller is in Pakistan, e.g. ['.pk website', 'Pakistani phone number'].
    Empty when the page shows none."""
    links = links or {}
    host = _host(url)
    text = text or ""
    found = []
    if host.endswith(".pk"):
        found.append(".pk website")

    phones = " ".join(links.get("phones") or [])
    if _PK_PHONE.search(phones) or _PK_PHONE.search(text):
        found.append("Pakistani phone number")

    india = bool(_INDIA.search(text)) or host.endswith(".in")
    shown = " ".join((links.get("prices") or {}).get("shown") or [])
    if currency == "PKR" or _PKR.search(text) or _PKR.search(shown):
        found.append("price in PKR")
    elif not india and (_RS.search(text) or _RS.search(shown)):
        found.append("price in PKR")

    city = _CITY.search(text)
    if city:
        found.append(f"address in {city.group(1).title()}")
    return found


def page_evidence(page: dict, currency: str | None = None) -> list[str]:
    return evidence(page.get("url", ""), f"{page.get('title', '')} {page.get('text', '')}", page.get("links"),
                    currency)

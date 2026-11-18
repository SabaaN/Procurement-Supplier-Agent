"""Reads one cleaned page with Groq and returns normalised product fields.

Facts come only from the page text. The model fills a loose schema; Python then normalises
names and units and checks that the price really appears on the page.
"""
import logging
import re
import time
from datetime import datetime, timezone

from pydantic import ValidationError

from ..config import settings
from ..devices import get_device
from . import llm

log = logging.getLogger(__name__)


# Bump when the extraction prompt or schema changes, so pages read with the old one are read again.
EXTRACTION_VERSION = 2


def cache_key(device_key: str) -> str:
    """The extraction cache's device key, versioned."""
    return f"{device_key}:v{EXTRACTION_VERSION}"


class ExtractionError(RuntimeError):
    """The model failed (or the key is missing). The page is skipped and not cached."""


SYSTEM = (
    "You extract product data from the text of one web page. Use ONLY facts stated in the page text. "
    "If a field is not stated, return null. Never guess, never infer from the product name, never use outside "
    "knowledge. Set is_product_page to true only if the page describes one specific product or model that can "
    "be bought; set it to false for category or listing pages, articles, blogs, manuals and company pages. "
    "Set is_listing_page to true for a shop's category, search-results or catalogue page that shows several "
    "products for sale. Set is_right_device_type as the device notes describe. "
    "For price give ONE unit as a plain number (no symbols or thousands separators) and the ISO currency code "
    "only if the page shows it clearly; otherwise null."
)


def _llm(model: str | None = None):
    if not settings.groq_api_key:
        raise ExtractionError("GROQ_API_KEY is not set (add it to backend/.env)")
    return llm.chat(model or settings.groq_model_small, 0.0)


def _prompt(device, url: str, title: str, text: str) -> str:
    return (
        f"Device type: {device.label}\n"
        f"Notes: {device.extraction_hint}\n"
        f"Page URL: {url}\n"
        f"Search result title: {title}\n\n"
        f"PAGE TEXT:\n{text}"
    )


def _invoke(device, url: str, title: str, text: str):
    """One structured Groq call, retried once. Returns an instance of device.extraction_model.
    Raises llm.DailyLimitReached (not retried) when every model is out for the day."""
    messages = [("system", SYSTEM), ("human", _prompt(device, url, title, text))]
    last = None
    for attempt in range(2):
        try:
            return llm.call(settings.groq_model_small, device.extraction_model, messages, client_for=_llm)
        except llm.DailyLimitReached:
            raise
        except Exception as e:  # per-minute rate limit, bad tool output, network...
            last = e
            log.warning("Extraction attempt %d failed for %s: %s: %s", attempt + 1, url, type(e).__name__, e)
            if attempt == 0:
                time.sleep(llm.per_minute_wait(e) or settings.extract_retry_wait)
    raise ExtractionError(f"{type(last).__name__}: {last}") from last


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_CURRENCY_NAMES = {"rs": "PKR", "rs.": "PKR", "\u20a8": "PKR", "\u20ac": "EUR", "\u00a3": "GBP"}


def _price_on_page(price: float, text: str) -> bool:
    """Is this number really written on the page? Guards against invented prices."""
    for match in _NUMBER.findall(text):
        try:
            if abs(float(match.replace(",", "")) - price) < 0.005:
                return True
        except ValueError:
            continue
    return False


def _currency(value: str | None) -> str | None:
    """ISO code as given, or a few unambiguous symbols. A bare '$' stays unknown (USD? CAD?)."""
    s = (value or "").strip()
    if re.fullmatch(r"[A-Za-z]{3}", s):
        return s.upper()
    return _CURRENCY_NAMES.get(s.lower())


PAGE_KINDS = ("product", "listing", "wrong_type", "other")


def extract_page(device_key: str, url: str, title: str, text: str) -> tuple[str, dict | None]:
    """(kind, product). kind is one of PAGE_KINDS; product is set only for 'product'.

    'listing'    a shop page listing several products: the caller can follow its product links
    'wrong_type' a product of another kind (e.g. a CCTV camera when the buyer wants machine vision)
    'other'      articles, manuals, company pages...
    Raises ExtractionError if the model failed."""
    return _extract(device_key, url, title, text)


def extract_product(device_key: str, url: str, title: str, text: str) -> dict | None:
    """The product on this page, or None if it isn't a (right-type) product page."""
    return _extract(device_key, url, title, text)[1]


def _extract(device_key: str, url: str, title: str, text: str) -> tuple[str, dict | None]:
    device = get_device(device_key)
    raw = _invoke(device, url, title, text)
    if getattr(raw, "is_right_device_type", None) is False:
        return "wrong_type", None
    if not raw.is_product_page:
        return ("listing" if getattr(raw, "is_listing_page", False) else "other"), None
    return "product", _build_product(device, raw, url, title, text)


def _build_product(device, raw, url: str, title: str, text: str) -> dict:
    data = raw.model_dump()
    fields, flags = device.normalize(data)

    price = data.get("price")
    if price is not None and (price < 0 or not _price_on_page(price, text)):
        flags.append("price_not_found_on_page")
        price = None
    moq = data.get("moq")

    try:
        spec = device.spec_model(
            title=(data.get("title") or title or url)[:200],
            source_url=url,
            supplier=data.get("supplier"),
            part_number=data.get("part_number"),
            price=price,
            currency=_currency(data.get("currency")) if price is not None else None,
            moq=moq if moq and moq >= 1 else None,
            fetched_at=datetime.now(timezone.utc),
            flags=flags,
            **fields,
        )
    except ValidationError as e:
        raise ExtractionError(f"extracted values failed validation ({e.error_count()} errors)") from e
    return spec.model_dump(mode="json")
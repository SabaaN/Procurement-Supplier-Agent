"""Reads one cleaned page with Groq and returns normalised product fields.

Facts come only from the page text. The model fills a loose schema; Python then normalises
names and units and checks that the price really appears on the page.
"""
import logging
import re
import time
from datetime import datetime, timezone
from functools import lru_cache

from pydantic import ValidationError

from ..config import settings
from ..devices import get_device

log = logging.getLogger(__name__)


class ExtractionError(RuntimeError):
    """The model failed (or the key is missing). The page is skipped and not cached."""


SYSTEM = (
    "You extract product data from the text of one web page. Use ONLY facts stated in the page text. "
    "If a field is not stated, return null. Never guess, never infer from the product name, never use outside "
    "knowledge. Set is_product_page to true only if the page describes one specific product or model that can "
    "be bought; set it to false for category or listing pages, articles, blogs, manuals and company pages. "
    "For price give ONE unit as a plain number (no symbols or thousands separators) and the ISO currency code "
    "only if the page shows it clearly; otherwise null."
)


@lru_cache(maxsize=1)
def _llm():
    if not settings.groq_api_key:
        raise ExtractionError("GROQ_API_KEY is not set (add it to backend/.env)")
    from langchain_groq import ChatGroq

    return ChatGroq(model=settings.groq_model_small, temperature=0, max_retries=2)


def _prompt(device, url: str, title: str, text: str) -> str:
    return (
        f"Device type: {device.label}\n"
        f"Notes: {device.extraction_hint}\n"
        f"Page URL: {url}\n"
        f"Search result title: {title}\n\n"
        f"PAGE TEXT:\n{text}"
    )


def _invoke(device, url: str, title: str, text: str):
    """One structured Groq call, retried once. Returns an instance of device.extraction_model."""
    structured = _llm().with_structured_output(device.extraction_model)
    messages = [("system", SYSTEM), ("human", _prompt(device, url, title, text))]
    last = None
    for attempt in range(2):
        try:
            return structured.invoke(messages)
        except Exception as e:  # rate limit, bad tool output, network...
            last = e
            log.warning("Extraction attempt %d failed for %s: %s: %s", attempt + 1, url, type(e).__name__, e)
            if attempt == 0:
                time.sleep(settings.extract_retry_wait)
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


def extract_product(device_key: str, url: str, title: str, text: str) -> dict | None:
    """A product dict (the device's spec model, dumped), or None if the page is not a product page.
    Raises ExtractionError if the model failed."""
    device = get_device(device_key)
    raw = _invoke(device, url, title, text)
    if not raw.is_product_page:
        return None

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
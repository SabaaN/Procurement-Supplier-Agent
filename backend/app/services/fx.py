"""Exchange rates from the free open.er-api.com endpoint, cached for 24 hours.

Rates By Exchange Rate API (https://www.exchangerate-api.com). The provider requires attribution
wherever converted prices are shown to users, so keep a link to it when we build the UI.
"""
import time

import httpx

from ..config import settings
from . import cache

URL = "https://open.er-api.com/v6/latest/USD"
RETRY_AFTER = 300  # seconds before trying the network again after a failed download
STALE_OK_HOURS = 24 * 7  # if the download fails, rates up to a week old are still better than nothing

_last_failure: float | None = None


def _fetch_usd_rates() -> dict | None:
    """Download today's USD-based rates. None on any failure."""
    try:
        resp = httpx.get(URL, timeout=settings.fetch_timeout)
        resp.raise_for_status()
        data = resp.json()
        rates = data.get("rates")
        if data.get("result") == "success" and isinstance(rates, dict) and rates:
            return rates
    except Exception:
        pass
    return None


def _usd_rates() -> dict | None:
    global _last_failure
    rates = cache.get_fx("USD")  # fresh (under 24 hours)
    if rates:
        return rates
    if _last_failure is None or time.monotonic() - _last_failure >= RETRY_AFTER:
        rates = _fetch_usd_rates()
        if rates:
            cache.put_fx(rates)
            return rates
        _last_failure = time.monotonic()
    return cache.get_fx("USD", max_age_hours=STALE_OK_HOURS)


def get_rate(from_cur: str, to_cur: str) -> float | None:
    """How many `to_cur` one `from_cur` buys, or None if we have no rate. Never raises."""
    from_cur, to_cur = from_cur.upper(), to_cur.upper()
    if from_cur == to_cur:
        return 1.0
    rates = _usd_rates()
    if not rates or not rates.get(from_cur) or not rates.get(to_cur):
        return None
    return rates[to_cur] / rates[from_cur]
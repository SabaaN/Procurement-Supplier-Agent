"""Turns the buyer's criteria into web search queries.

Primary path: a small Groq model writes the queries.
Fallback: plain template queries, so a Groq error or rate limit never stops a search.
"""
import logging

from pydantic import BaseModel, Field

from ..config import settings
from ..devices import get_device
from . import llm

log = logging.getLogger(__name__)


class QueryPlan(BaseModel):
    queries: list[str] = Field(description="3 to 5 distinct web search queries")


SYSTEM = (
    "You write web search queries that find shop pages where a buyer can see the price of, and buy, "
    "the industrial equipment they want: product pages and shop category pages from distributors and "
    "online stores. Do not write queries for datasheets, PDFs, manuals, reviews or news. "
    "Return 3 to 5 distinct, short queries, each written the way a person would type it into a search "
    "engine. Use only the specs you are given. Never invent specs, models or prices."
)

# Where buyers paying in these currencies usually shop, so at least one query finds local sellers.
LOCAL_MARKET = {"PKR": "Pakistan", "AED": "UAE", "INR": "India", "GBP": "UK", "EUR": "Europe"}


def spec_items(device, criteria: dict) -> list[dict]:
    """The specs the buyer asked for, as readable items:
    {label, text (for the prompt), term (for template queries), required}."""
    items = []
    for f in device.fields:
        req = criteria.get(f.name)
        if not (isinstance(req, dict) and "value" in req):
            continue  # not asked for (also skips budget/quantity, which are plain numbers)
        value = req["value"]
        if isinstance(value, bool):
            vtxt, term = ("yes" if value else "no"), (f.label.lower() if value else "")
        else:
            vtxt = " / ".join(map(str, value)) if isinstance(value, list) else f"{value:g}" if isinstance(value, (int, float)) else str(value)
            unit = f" {f.unit}" if f.unit else ""
            term = f"{vtxt}{unit}".replace(" / ", " ")
            if f.kind in ("select", "multiselect"):
                term += f" {f.label.lower()}"
        op = "at least " if f.name.startswith("min_") else "at most " if f.name.startswith("max_") else ""
        flexible = bool(req.get("flexible"))
        items.append(
            {
                "label": f.label,
                "text": f"{f.label}: {'about ' if flexible and op else op}{vtxt}{f' {f.unit}' if f.unit else ''}",
                "term": term,
                "required": bool(req["required"]) and not flexible,
                "level": "flexible" if flexible else "must" if req["required"] else "nice",
            }
        )
    return items


def fallback_queries(device, items: list[dict], attempt: int, criteria: dict | None = None) -> list[str]:
    """Template queries. Flexible specs are never in them (so nearby values are found too);
    later attempts drop must-have specs one by one to widen the search."""
    name = device.search_term or f"industrial {device.label.lower()}"
    market = LOCAL_MARKET.get((criteria or {}).get("currency", ""))
    required = [i["term"] for i in items if i["level"] == "must" and i["term"]]
    nice = [i["term"] for i in items if i["level"] == "nice" and i["term"]]
    if attempt == 1:
        terms = " ".join(required or nice[:2])
    else:
        terms = " ".join(required[: max(1, len(required) - (attempt - 1))] if required else [])
    queries = [f"{name} {terms} price", f"{name} {terms} buy online"]
    if market:
        queries.insert(0, f"{name} {terms} price in {market}")
    return [" ".join(q.split()) for q in queries]


def _prompt(device, items: list[dict], criteria: dict, attempt: int, previous) -> str:
    def group(level):
        return "\n".join(f"- {i['text']}" for i in items if i["level"] == level) or "- (none)"

    lo, hi = criteria.get("budget_min"), criteria.get("budget_max")
    market = LOCAL_MARKET.get(criteria.get("currency", ""))
    parts = [
        f"Device: {device.label}",
        device.search_hint,
        "Required specs:\n" + group("must"),
        "Flexible specs (the buyer accepts nearby values: do NOT put these numbers in the queries):\n"
        + group("flexible"),
        "Preferred specs:\n" + group("nice"),
        f"Budget per unit: {lo if lo is not None else 'any'} to {hi if hi is not None else 'any'} {criteria.get('currency', '')}; "
        f"quantity {criteria.get('quantity', 1)}",
    ]
    if criteria.get("notes"):
        parts.append(f"Buyer notes: {criteria['notes']}")
    if market:
        parts.append(f"The buyer is in {market}: make at least one query find shops selling there "
                     f"(e.g. ending in 'price in {market}').")
    if attempt == 1:
        parts.append("Be specific: include the most important required specs in the queries.")
    else:
        parts.append(
            "Earlier queries found too few matching products. Be broader: drop the preferred specs and "
            "the strictest required spec, and try different product-type words.\n"
            "Do not repeat these queries:\n" + "\n".join(f"- {q}" for q in previous)
        )
    return "\n\n".join(parts)


def _llm(model: str | None = None):
    # Reads GROQ_API_KEY from the environment (loaded from .env by app.config).
    return llm.chat(model or settings.groq_model_small, 0.2)


def _llm_queries(device, items, criteria, attempt, previous) -> list[str]:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set (add it to backend/.env)")
    messages = [("system", SYSTEM), ("human", _prompt(device, items, criteria, attempt, previous))]
    plan = llm.call(settings.groq_model_small, QueryPlan, messages, client_for=_llm)
    return plan.queries


def _clean(queries: list[str], previous) -> list[str]:
    """Trim, drop blanks and repeats (including earlier attempts), cap the count."""
    seen = {q.lower() for q in previous}
    out = []
    for q in queries:
        q = " ".join(str(q).split())
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
    return out[: settings.max_queries]


def plan(device_key: str, criteria: dict, attempt: int, previous=()) -> tuple[list[str], str]:
    """Returns (queries, source) where source is 'llm' or 'fallback: <why>'."""
    device = get_device(device_key)
    items = spec_items(device, criteria)
    try:
        queries = _clean(_llm_queries(device, items, criteria, attempt, previous), previous)
        if not queries:
            raise ValueError("model returned no new queries")
        return queries, "llm"
    except Exception as e:  # any Groq failure: missing key, rate limit, bad model name, bad output
        log.warning("Query planner fell back to templates: %s: %s", type(e).__name__, e)
        return _clean(fallback_queries(device, items, attempt, criteria), previous), f"fallback: {type(e).__name__}"
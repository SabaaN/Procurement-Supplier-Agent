"""Turns the buyer's criteria into web search queries.

Primary path: a small Groq model writes the queries.
Fallback: plain template queries, so a Groq error or rate limit never stops a search.
"""
import logging
from functools import lru_cache

from pydantic import BaseModel, Field

from ..config import settings
from ..devices import get_device

log = logging.getLogger(__name__)


class QueryPlan(BaseModel):
    queries: list[str] = Field(description="3 to 5 distinct web search queries")


SYSTEM = (
    "You write web search queries that find product pages (store listings or datasheets) "
    "for industrial equipment a buyer wants to purchase. Return 3 to 5 distinct, short queries, "
    "each written the way a person would type it into a search engine. "
    "Use only the specs you are given. Never invent specs, models or prices."
)


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
        op = "at least " if f.name.startswith("min_") else ""
        items.append(
            {
                "label": f.label,
                "text": f"{f.label}: {op}{vtxt}{f' {f.unit}' if f.unit else ''}",
                "term": term,
                "required": bool(req["required"]),
            }
        )
    return items


def fallback_queries(device_label: str, items: list[dict], attempt: int) -> list[str]:
    """Template queries. Later attempts drop required specs one by one to widen the search."""
    name = f"industrial {device_label.lower()}"
    required = [i["term"] for i in items if i["required"] and i["term"]]
    preferred = [i["term"] for i in items if not i["required"] and i["term"]]
    if attempt == 1:
        terms = " ".join(required or preferred[:2])
        return [f"{name} {terms} buy", f"{name} {terms} datasheet"]
    keep = max(1, len(required) - (attempt - 1)) if required else 0
    terms = " ".join(required[:keep])
    return [f"{name} {terms} price", f"{device_label.lower()} supplier {terms}"]


def _prompt(device_label: str, items: list[dict], criteria: dict, attempt: int, previous) -> str:
    required = [i["text"] for i in items if i["required"]] or ["(none)"]
    preferred = [i["text"] for i in items if not i["required"]] or ["(none)"]
    lo, hi = criteria.get("budget_min"), criteria.get("budget_max")
    parts = [
        f"Device: {device_label}",
        "Required specs:\n" + "\n".join(f"- {t}" for t in required),
        "Preferred specs:\n" + "\n".join(f"- {t}" for t in preferred),
        f"Budget per unit: {lo if lo is not None else 'any'} to {hi if hi is not None else 'any'} {criteria.get('currency', '')}; "
        f"quantity {criteria.get('quantity', 1)}",
    ]
    if criteria.get("notes"):
        parts.append(f"Buyer notes: {criteria['notes']}")
    if attempt == 1:
        parts.append("Be specific: include the most important required specs in the queries.")
    else:
        parts.append(
            "Earlier queries found too few matching products. Be broader: drop the preferred specs and "
            "the strictest required spec, and try different product-type words.\n"
            "Do not repeat these queries:\n" + "\n".join(f"- {q}" for q in previous)
        )
    return "\n\n".join(parts)


@lru_cache(maxsize=1)
def _llm():
    from langchain_groq import ChatGroq

    # Reads GROQ_API_KEY from the environment (loaded from .env by app.config).
    return ChatGroq(model=settings.groq_model_small, temperature=0.2, max_retries=2)


def _llm_queries(device_label, items, criteria, attempt, previous) -> list[str]:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set (add it to backend/.env)")
    structured = _llm().with_structured_output(QueryPlan)
    plan = structured.invoke([("system", SYSTEM), ("human", _prompt(device_label, items, criteria, attempt, previous))])
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
        queries = _clean(_llm_queries(device.label, items, criteria, attempt, previous), previous)
        if not queries:
            raise ValueError("model returned no new queries")
        return queries, "llm"
    except Exception as e:  # any Groq failure: missing key, rate limit, bad model name, bad output
        log.warning("Query planner fell back to templates: %s: %s", type(e).__name__, e)
        return _clean(fallback_queries(device.label, items, attempt), previous), f"fallback: {type(e).__name__}"
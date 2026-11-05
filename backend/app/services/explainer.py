"""Plain-language "why it ranked here" text for each product.

Facts (specs, prices, met/missed requirements, flags) are assembled in Python. One Groq call turns
them into short comparative explanations. Every number in the model's text must already appear in
the facts; otherwise that explanation is replaced by a template written from the same facts, so the
model can phrase things but never introduces a spec or a price.
"""
import json
import logging
import re
from functools import lru_cache

from pydantic import BaseModel

from ..config import settings
from ..devices import get_device
from ..devices.base import ProductBase

log = logging.getLogger(__name__)


class Explanation(BaseModel):
    rank: int
    text: str


class ExplanationSet(BaseModel):
    items: list[Explanation]


SYSTEM = (
    "You explain a ranked shortlist of products to a buyer. For each product write 1 or 2 plain sentences "
    "saying why it has this rank: lead with its strongest matches, then mention any missed requirement or "
    "data issue the buyer should check. Use ONLY the facts provided. Copy numbers exactly as written: never "
    "round, convert or invent numbers, specs or claims. You may compare a product with the others in the list. "
    "Scores are out of 100. Return one item per product, using its rank number."
)

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[float]:
    out = set()
    for m in _NUMBER.findall(text):
        try:
            out.add(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def _money(value, currency: str, exact: bool = False) -> str | None:
    """Format an amount. Big converted totals are shown in whole units; `exact` keeps the cents."""
    if value is None:
        return None
    text = f"{value:,.2f}" if exact or abs(value) < 1000 else f"{value:,.0f}"
    return f"{text} {currency}".strip()


def facts_for(device_key: str | None, p: dict, rank: int, total: int, criteria: dict) -> dict:
    """Everything the model may mention about one product."""
    spec_fields = set()
    if device_key:
        spec_fields = set(get_device(device_key).spec_model.model_fields) - set(ProductBase.model_fields)
    specs = {k: p[k] for k in sorted(spec_fields) if p.get(k) not in (None, [], "")}
    buyer_cur = criteria.get("currency", "")
    fact = {
        "rank": rank,
        "of": total,
        "title": p.get("title"),
        "supplier": p.get("supplier"),
        "score": p.get("match_score"),
        "quantity": criteria.get("quantity", 1),
        "price_on_page": _money(p.get("price"), p.get("currency") or "", exact=True),
        "total_for_quantity": _money(p.get("total_cost"), buyer_cur),
        "meets": p.get("requirements_met", []),
        "misses": p.get("requirements_missed", []),
        "issues": p.get("flags", []),
        "specs": specs,
        "score_breakdown": p.get("score_breakdown", {}),
    }
    return {k: v for k, v in fact.items() if v not in (None, [], {}, "")}


def template_explanation(p: dict, rank: int, total: int, criteria: dict) -> str:
    """Plain explanation written from the facts alone. Used when the model fails or breaks the rules."""
    score = p.get("match_score")
    head = f"Ranked #{rank} of {total}"
    parts = [head + (f" with a match score of {score:.0f}/100." if score is not None else ".")]
    if p.get("requirements_met"):
        parts.append("Meets: " + ", ".join(p["requirements_met"]) + ".")
    if p.get("requirements_missed"):
        parts.append("Misses: " + ", ".join(p["requirements_missed"]) + ".")
    total_cost = _money(p.get("total_cost"), criteria.get("currency", ""))
    if total_cost:
        parts.append(f"About {total_cost} for {criteria.get('quantity', 1)} units (excluding shipping and duties).")
    elif p.get("price") is None:
        parts.append("No price was found on the page.")
    if p.get("flags"):
        parts.append("Check: " + "; ".join(p["flags"][:3]) + ".")
    return " ".join(parts)


@lru_cache(maxsize=1)
def _llm():
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set (add it to backend/.env)")
    from langchain_groq import ChatGroq

    return ChatGroq(model=settings.groq_model_large, temperature=0.2, max_retries=2)


def _llm_explanations(facts: list[dict]) -> dict[int, str]:
    """One Groq call for the whole shortlist. Returns {rank: text}."""
    structured = _llm().with_structured_output(ExplanationSet)
    result = structured.invoke([("system", SYSTEM), ("human", json.dumps(facts, ensure_ascii=False, indent=1))])
    return {item.rank: item.text for item in result.items}


def explain(device_key: str | None, criteria: dict, ranked: list[dict]) -> tuple[list[str], str]:
    """One explanation per product, in ranked order, plus where they came from ('llm' or a template note)."""
    total = len(ranked)
    texts = [template_explanation(p, i + 1, total, criteria) for i, p in enumerate(ranked)]
    facts = [facts_for(device_key, p, i + 1, total, criteria) for i, p in enumerate(ranked[: settings.explain_top_n])]
    if not facts:
        return texts, "llm"

    try:
        by_rank = _llm_explanations(facts)
    except Exception as e:  # missing key, rate limit, wrong model name, bad output...
        log.warning("Explanations fell back to templates: %s: %s", type(e).__name__, e)
        return texts, f"templates: {type(e).__name__}"

    allowed = _numbers(json.dumps(facts, ensure_ascii=False)) | {100.0}  # scores are out of 100
    accepted = 0
    for i in range(len(facts)):
        text = (by_rank.get(i + 1) or "").strip()
        if text and _numbers(text) <= allowed:
            texts[i] = text
            accepted += 1
        elif text:
            log.warning("Explanation for rank %d used numbers that are not in the facts; using template", i + 1)
    if accepted == len(facts):
        return texts, "llm"
    return texts, f"llm: {accepted}/{len(facts)} accepted, rest templates"
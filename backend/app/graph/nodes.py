"""Graph nodes. No LangGraph imports here, so every node is a plain function you can unit test.

STUB nodes (plan_queries, search, fetch_clean, extract, score) return fake data so the whole
graph can run end to end. We replace them one at a time in later steps.
"""
from pydantic import ValidationError

from ..devices import UnsupportedDevice, get_device
from .progress import emit
from .state import SearchState

MIN_RESULTS = 5  # fewer survivors than this -> plan broader queries
MAX_ATTEMPTS = 3  # never loop more than this many times


# ---------- parent graph ----------

def parse_requirements(state: SearchState) -> dict:
    """Validate the form input against the chosen device's criteria model. No LLM needed."""
    emit("parse", "running", "Checking your requirements")
    try:
        device = get_device(state["device_type"])
        criteria = device.criteria_model.model_validate(state.get("raw_criteria", {}))
    except UnsupportedDevice as e:
        emit("parse", "failed", str(e))
        return {"error": str(e)}
    except ValidationError as e:
        msg = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
        emit("parse", "failed", msg)
        return {"error": msg}
    emit("parse", "done", "Requirements accepted")
    return {"criteria": criteria.model_dump(mode="json"), "attempts": 0, "error": None}


def route_device(state: SearchState) -> str:
    """Conditional edge: plain Python, no LLM."""
    return "error" if state.get("error") else state["device_type"]


def finalize(state: SearchState) -> dict:
    emit("rank", "running", "Ranking results")
    ranked = sorted(
        state.get("candidates", []),
        key=lambda p: (-(p.get("match_score") or 0), p.get("price") if p.get("price") is not None else float("inf")),
    )
    emit("rank", "done", f"{len(ranked)} products ranked", done=len(ranked), total=len(ranked))
    return {"ranked": ranked}


# ---------- device subgraph (shared by every device) ----------

def plan_queries(state: SearchState) -> dict:  # STUB
    attempt = state.get("attempts", 0) + 1
    device = get_device(state["device_type"])
    emit("search", "running", f"Planning search queries (attempt {attempt})")
    queries = [f"buy {device.label.lower()} industrial"]
    if attempt == 1:
        queries.append(f"{device.label.lower()} with all required specs")
    return {"queries": queries, "attempts": attempt}


def search(state: SearchState) -> dict:  # STUB
    n = 3 if state["attempts"] == 1 else 8  # broader queries find more pages
    urls = [f"https://example.com/{state['device_type']}/{i}" for i in range(n)]
    emit("search", "done", f"Found {len(urls)} pages", done=len(urls), total=len(urls))
    return {"urls": urls}


def fetch_clean(state: SearchState) -> dict:  # STUB
    pages = [{"url": u, "text": "stub page text"} for u in state["urls"]]
    return {"pages": pages}


def extract(state: SearchState) -> dict:  # STUB
    device = get_device(state["device_type"])
    products = []
    for i, page in enumerate(state["pages"]):
        emit("extract", "running", f"Reading {i + 1} of {len(state['pages'])} pages", done=i + 1, total=len(state["pages"]))
        products.append(device.stub_spec(i, page["url"]).model_dump(mode="json"))
    emit("extract", "done", f"Extracted {len(products)} products")
    return {"products": products}


def filter_products(state: SearchState) -> dict:
    """Python filter. Only the budget check so far; required-spec checks come next step."""
    c = state["criteria"]
    lo, hi = c.get("budget_min"), c.get("budget_max")
    kept = []
    for p in state["products"]:
        price = p.get("price")
        if price is None:
            kept.append({**p, "flags": [*p.get("flags", []), "price_missing"]})
        elif (lo is None or price >= lo) and (hi is None or price <= hi):
            kept.append(p)
    emit("filter", "done", f"{len(kept)} of {len(state['products'])} products kept", done=len(kept), total=len(state["products"]))
    return {"candidates": kept}


def route_after_filter(state: SearchState) -> str:
    """Too few survivors -> plan broader queries, unless we've already tried enough."""
    if len(state["candidates"]) >= MIN_RESULTS or state["attempts"] >= MAX_ATTEMPTS:
        return "score"
    return "plan_queries"


def score(state: SearchState) -> dict:  # STUB
    return {"candidates": [{**p, "match_score": 50.0} for p in state["candidates"]]}

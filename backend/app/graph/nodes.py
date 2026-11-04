"""Graph nodes. No LangGraph imports here, so every node is a plain function you can unit test.

STUB nodes (plan_queries, search, fetch_clean, extract, score) return fake data so the whole
graph can run end to end. We replace them one at a time in later steps.
"""
from pydantic import ValidationError

from ..devices import UnsupportedDevice, get_device
from .progress import emit
from .state import SearchState
from ..services import query_planner, web_search
from .checks import check_product
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..config import settings
from ..services import cache, extractor, page_fetcher, query_planner, web_search
from ..services import cache, extractor, fx, page_fetcher, query_planner, web_search
from . import scoring

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

def plan_queries(state: SearchState) -> dict:
    """Groq writes the queries (template fallback if it fails). Later attempts go broader."""
    attempt = state.get("attempts", 0) + 1
    emit("search", "running", f"Planning search queries (attempt {attempt})")
    past = state.get("past_queries", [])
    queries, source = query_planner.plan(state["device_type"], state["criteria"], attempt, past)
    note = "" if source == "llm" else f" ({source})"
    emit("search", "running", f"Planned {len(queries)} queries{note}")
    return {"queries": queries, "past_queries": [*past, *queries], "attempts": attempt}


def search(state: SearchState) -> dict:
    """Run each planned query on Tavily; keep only URLs we haven't seen in earlier attempts."""
    urls = list(state.get("urls", []))
    hits = list(state.get("hits", []))
    known = set(urls)
    errors = []
    for q in state.get("queries", []):
        try:
            results = web_search.search_web(q)
        except web_search.SearchError as e:
            errors.append(str(e))
            continue
        for r in results:
            if r["url"] not in known:
                known.add(r["url"])
                urls.append(r["url"])
                hits.append({**r, "query": q})

    new = len(urls) - len(state.get("urls", []))
    if errors and len(errors) == len(state.get("queries", [])):
        emit("search", "failed", f"Search failed: {errors[0]}")
        return {"urls": urls, "hits": hits, "error": f"Search failed: {errors[0]}"}
    emit("search", "done", f"Found {new} new pages ({len(urls)} total)", done=len(urls), total=len(urls))
    return {"urls": urls, "hits": hits}


def fetch_clean(state: SearchState) -> dict:
    """Download and clean up to N pages we haven't tried yet. Cached results skip the network."""
    pages = list(state.get("pages", []))
    tried = {p["url"] for p in pages}
    titles = {h["url"]: h.get("title", "") for h in state.get("hits", [])}
    todo = [u for u in state.get("urls", []) if u not in tried][: settings.max_pages_per_attempt]
    if not todo:
        emit("extract", "done", "No new pages to read")
        return {"pages": pages}

    results, to_fetch = {}, []
    for url in todo:
        cached = cache.get_page(url)
        if cached:
            results[url] = cached
        else:
            to_fetch.append(url)

    done = len(results)
    if to_fetch:
        with ThreadPoolExecutor(max_workers=settings.fetch_workers) as pool:
            futures = [pool.submit(page_fetcher.fetch_page, u) for u in to_fetch]
            for fut in as_completed(futures):
                r = fut.result()  # fetch_page never raises
                if r.ok or r.error != "timeout":  # timeouts are often temporary: don't cache them
                    cache.put_page(r.url, r.ok, r.text, r.error)
                results[r.url] = {"url": r.url, "ok": r.ok, "text": r.text, "error": r.error}
                done += 1
                emit("extract", "running", f"Reading {done} of {len(todo)} pages", done=done, total=len(todo))

    for url in todo:
        pages.append({**results[url], "title": titles.get(url, "")})
    ok = sum(1 for url in todo if results[url]["ok"])
    emit("extract", "running", f"Fetched {ok} of {len(todo)} pages ({len(todo) - ok} unreachable)")
    return {"pages": pages}


def extract(state: SearchState) -> dict:
    """Groq reads each fetched page. Results (including 'not a product page') are cached by URL."""
    device_key = state["device_type"]
    pages = [p for p in state["pages"] if p["ok"]]  # skip pages that failed to download
    products, skipped, failed, last_error = [], 0, 0, ""
    for i, page in enumerate(pages, 1):
        emit("extract", "running", f"Extracting specs from page {i} of {len(pages)}", done=i, total=len(pages))
        cached = cache.get_extraction(page["url"], device_key)
        if cached is not None:
            product = cached["product"]
        else:
            try:
                product = extractor.extract_product(device_key, page["url"], page.get("title", ""), page["text"])
            except extractor.ExtractionError as e:
                failed, last_error = failed + 1, str(e)
                continue  # not cached, so a later attempt can retry it
            cache.put_extraction(page["url"], device_key, product)
        if product is None:
            skipped += 1
        else:
            products.append(product)

    if pages and failed == len(pages):  # the model never worked: stop instead of looping
        emit("extract", "failed", f"Extraction failed: {last_error}")
        return {"products": [], "error": f"Extraction failed: {last_error}"}
    emit("extract", "done", f"{len(products)} products extracted ({skipped} not product pages, {failed} failed)")
    return {"products": products}

def convert_prices(state: SearchState) -> dict:
    """Put each price in the buyer's currency and work out the cost for the requested quantity."""
    c = state["criteria"]
    buyer_cur, qty = c.get("currency"), c.get("quantity", 1)
    out = []
    for p in state["products"]:
        price, cur = p.get("price"), p.get("currency")
        flags = list(p.get("flags", []))
        price_buyer, rate = None, None
        if price is not None:
            if not cur or not buyer_cur or cur == buyer_cur:
                price_buyer = price  # same currency, or unknown (the filter flags that case)
            else:
                rate = fx.get_rate(cur, buyer_cur)
                price_buyer = round(price * rate, 2) if rate else None
        moq = p.get("moq")
        if moq and qty < moq:
            flags.append(f"MOQ {moq} is above your quantity {qty}")
        out.append({
            **p,
            "price_buyer": price_buyer,
            "fx_rate": round(rate, 4) if rate else None,
            "total_cost": round(price_buyer * qty, 2) if price_buyer is not None else None,
            "flags": flags,
        })
    emit("filter", "running", f"Checked prices against your budget in {buyer_cur or 'its own currency'}")
    return {"products": out}

def filter_products(state: SearchState) -> dict:
    """Python filter: budget (in the buyer's currency), then every requirement the buyer set."""
    c = state["criteria"]
    lo, hi = c.get("budget_min"), c.get("budget_max")
    buyer_cur = c.get("currency")
    kept, dropped = [], []
    for p in state["products"]:
        flags = list(p.get("flags", []))
        price, cur = p.get("price"), p.get("currency")
        # Price in the buyer's currency. convert_prices sets it; this is the fallback if it didn't run.
        if "price_buyer" in p:
            price_buyer = p["price_buyer"]
        else:
            price_buyer = price if (not cur or not buyer_cur or cur == buyer_cur) else None

        if price is None:
            flags.append("price_missing")
        elif price_buyer is None:
            flags.append(f"price in {cur}: budget not checked (no exchange rate)")
        else:
            if cur is None:
                flags.append("currency_unknown")
            if (lo is not None and price_buyer < lo) or (hi is not None and price_buyer > hi):
                dropped.append({"title": p.get("title"), "reasons": ["Price outside budget"]})
                continue

        verdict = check_product(c, p)
        if verdict["dropped_for"]:
            dropped.append({"title": p.get("title"), "reasons": verdict["dropped_for"]})
            continue

        flags += [f"{label}: not found on page" for label in verdict["unknown"]]
        kept.append({
            **p,
            "requirements_met": verdict["met"],
            "requirements_missed": verdict["missed"],
            "flags": flags,
        })

    emit("filter", "done", f"{len(kept)} of {len(state['products'])} products kept",
         done=len(kept), total=len(state["products"]))
    return {"candidates": kept, "dropped": dropped}


def route_after_filter(state: SearchState) -> str:
    """Too few survivors -> plan broader queries, unless we've already tried enough."""
    if state.get("error") or len(state["candidates"]) >= MIN_RESULTS or state["attempts"] >= MAX_ATTEMPTS:
        return "score"  # also stop when a step failed outright (e.g. Tavily key missing)
    return "plan_queries"


def score(state: SearchState) -> dict:
    """Real scoring: preferences, relative price and data confidence (see scoring.py)."""
    return {"candidates": scoring.score_products(state["criteria"], state["candidates"])}
"""Graph nodes. No LangGraph imports here, so every node is a plain function you can unit test.

STUB nodes (plan_queries, search, fetch_clean, extract, score) return fake data so the whole
graph can run end to end. We replace them one at a time in later steps.
"""
from collections import Counter

from pydantic import ValidationError

from ..devices import UnsupportedDevice, get_device
from .progress import emit
from .state import SearchState
from ..services import query_planner, web_search
from .checks import check_product
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..config import settings
from ..services import cache, contacts, explainer, extractor, fx, page_fetcher, query_planner, web_search
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
    """Sort by score (cheaper first on ties) and attach a plain-language explanation to each product."""
    emit("rank", "running", "Ranking results")

    def sort_key(p):
        cost = p.get("price_buyer") if p.get("price_buyer") is not None else p.get("price")
        # closest matches: fewest misses first, then score
        return (len(p.get("misses", [])), -(p.get("match_score") or 0), cost if cost is not None else float("inf"))

    ranked = sorted(state.get("candidates", []), key=sort_key)
    texts, source = explainer.explain(state.get("device_type"), state.get("criteria", {}), ranked)
    ranked = [{**p, "explanation": text} for p, text in zip(ranked, texts)]
    note = "" if source == "llm" else f" ({source})"
    emit("rank", "done", f"{len(ranked)} products ranked{note}", done=len(ranked), total=len(ranked))
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


def _fetch(urls: list[str], titles: dict, label: str = "pages") -> list[dict]:
    """Download and clean these URLs (cached results skip the network). Returns one page dict per URL."""
    results, to_fetch = {}, []
    for url in urls:
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
                    cache.put_page(r.url, r.ok, r.text, r.error, r.links)
                results[r.url] = {"url": r.url, "ok": r.ok, "text": r.text, "error": r.error, "links": r.links}
                done += 1
                emit("extract", "running", f"Reading {done} of {len(urls)} {label}", done=done, total=len(urls))
    return [{**results[url], "title": titles.get(url, "")} for url in urls]


def fetch_clean(state: SearchState) -> dict:
    """Download and clean up to N pages we haven't tried yet. Cached results skip the network."""
    pages = list(state.get("pages", []))
    tried = {p["url"] for p in pages}
    titles = {h["url"]: h.get("title", "") for h in state.get("hits", [])}
    todo = [u for u in state.get("urls", []) if u not in tried][: settings.max_pages_per_attempt]
    if not todo:
        emit("extract", "done", "No new pages to read")
        return {"pages": pages}

    new = _fetch(todo, titles)
    ok = sum(1 for p in new if p["ok"])
    emit("extract", "running", f"Fetched {ok} of {len(todo)} pages ({len(todo) - ok} unreachable)")
    return {"pages": pages + new}


def _extract_pages(device_key: str, pages: list[dict], label: str = "page") -> tuple[list, Counter, str]:
    """Run (or reuse cached) extraction on each page. Returns ([(page, kind, product)], kind counts, last error)."""
    key = extractor.cache_key(device_key)
    out, counts, last_error = [], Counter(), ""
    for i, page in enumerate(pages, 1):
        emit("extract", "running", f"Extracting specs from {label} {i} of {len(pages)}", done=i, total=len(pages))
        cached = cache.get_extraction(page["url"], key)
        if cached is not None:
            kind, product = cached["kind"], cached["product"]
        else:
            try:
                kind, product = extractor.extract_page(device_key, page["url"], page.get("title", ""), page["text"])
            except extractor.ExtractionError as e:
                counts["failed"] += 1
                last_error = str(e)
                continue  # not cached, so a later attempt can retry it
            cache.put_extraction(page["url"], key, product, kind)
        counts[kind] += 1
        if product is not None:
            # contacts and datasheet come from the page's links, so cached extractions get them too
            product = contacts.enrich(product, page.get("links"))
        out.append((page, kind, product))
    return out, counts, last_error


def _listing_links(results: list, known: set[str]) -> list[str]:
    """Product links found on listing pages, a few per page, not seen before, capped per attempt."""
    links = []
    for page, kind, _ in results:
        if kind != "listing":
            continue
        fresh = [u for u in (page.get("links") or {}).get("products", []) if u not in known and u not in links]
        links += fresh[: settings.listing_links_per_page]
    return links[: settings.max_followed_per_attempt]


def _kind_summary(counts: Counter) -> str:
    names = [("listing", "listing pages"), ("wrong_type", "wrong kind of product"),
             ("other", "not product pages"), ("failed", "failed")]
    return ", ".join(f"{counts[k]} {name}" for k, name in names if counts[k]) or "nothing else"


def extract(state: SearchState) -> dict:
    """Groq reads each fetched page (cached by URL). Product links on listing pages are then
    read one level deeper, so a shop's "5MP cameras - 24 items" page turns into products."""
    device_key = state["device_type"]
    pages = list(state["pages"])
    ok_pages = [p for p in pages if p["ok"]]  # skip pages that failed to download
    results, counts, last_error = _extract_pages(device_key, ok_pages)

    if ok_pages and counts["failed"] == len(ok_pages):  # the model never worked: stop instead of looping
        emit("extract", "failed", f"Extraction failed: {last_error}")
        return {"products": [], "error": f"Extraction failed: {last_error}"}

    urls = list(state.get("urls", []))
    follow = _listing_links(results, set(urls) | {p["url"] for p in pages})
    if follow:
        emit("extract", "running", f"Following {len(follow)} product links from {counts['listing']} listing pages")
        titles = {u: "" for u in follow}
        followed = _fetch(follow, titles, label="product links")
        pages += followed
        urls += follow
        more, more_counts, _ = _extract_pages(device_key, [p for p in followed if p["ok"]], label="linked page")
        results += more
        counts.update(more_counts)

    products = [product for _, kind, product in results if product is not None]
    emit("extract", "done", f"{len(products)} products extracted ({_kind_summary(counts)})")
    return {"products": products, "pages": pages, "urls": urls}


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
    """Python filter: budget (in the buyer's currency), then every requirement the buyer set.

    Cheaper than budget_min is kept (flagged if suspiciously cheap); over budget_max is dropped,
    unless the budget is flexible and it is within BUDGET_TOLERANCE. Dropped products are kept
    aside with their reasons, so the closest ones can be shown when nothing matches fully.
    """
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

        reasons, over = [], 0.0
        if price is None:
            flags.append("price_missing")
        elif price_buyer is None:
            flags.append(f"price in {cur}: budget not checked (no exchange rate)")
        else:
            if cur is None:
                flags.append("currency_unknown")
            if hi is not None and price_buyer > hi:
                over = (price_buyer - hi) / hi if hi else float("inf")
                if c.get("flexible_budget") and over <= settings.budget_tolerance:
                    flags.append(f"{over:.0%} over budget")
                else:
                    reasons.append(f"Price above budget ({over:.0%} over)" if hi else "Price above budget")
            if lo and price_buyer < lo * settings.cheap_ratio:
                flags.append("unusually cheap for your budget: check it is genuine and the right type")

        verdict = check_product(c, p, strict=settings.strict_requirements, tolerance=settings.flexible_tolerance)
        reasons += verdict["dropped_for"]
        flags += [f"{label}: not found on page" for label in verdict["unknown"]]
        product = {
            **p,
            "requirements_met": verdict["met"],
            "requirements_missed": verdict["missed"],
            "requirements_close": verdict["close"],
            "close_notes": verdict["close_notes"],
            "flags": flags,
        }
        if reasons:
            # how far off: each failed rule counts 1, plus how far over budget
            dropped.append({"title": p.get("title"), "reasons": reasons,
                            "distance": len(reasons) + min(over, 5), "product": product})
        else:
            kept.append(product)

    emit("filter", "done", f"{len(kept)} of {len(state['products'])} products kept{_drop_summary(dropped)}",
         done=len(kept), total=len(state["products"]))
    return {"candidates": kept, "dropped": dropped}


def _drop_summary(dropped: list[dict]) -> str:
    """' (dropped: 3 price outside budget, 1 frame rate: does not meet requirement)' for the progress panel."""
    counts: dict[str, int] = {}
    for d in dropped:
        reason = d["reasons"][0].split(" (")[0].split(":")[0] if d.get("reasons") else "other"
        counts[reason] = counts.get(reason, 0) + 1
    if not counts:
        return ""
    parts = [f"{n} {reason[0].lower() + reason[1:]}" for reason, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    return f" (dropped: {', '.join(parts)})"


def route_after_filter(state: SearchState) -> str:
    """Too few survivors -> plan broader queries, unless we've already tried enough."""
    if state.get("error") or len(state["candidates"]) >= MIN_RESULTS or state["attempts"] >= MAX_ATTEMPTS:
        return "score"  # also stop when a step failed outright (e.g. Tavily key missing)
    return "plan_queries"


NEAR_MISS_PENALTY = 15  # match points removed per miss, so a closest match never looks like a full one


def closest_matches(dropped: list[dict], n: int) -> list[dict]:
    """The n dropped products that came nearest, each marked near_miss with what it misses."""
    nearest = sorted(dropped, key=lambda d: d.get("distance", len(d["reasons"])))[:n]
    return [{**d["product"], "near_miss": True, "misses": d["reasons"]} for d in nearest if d.get("product")]


def score(state: SearchState) -> dict:
    """Real scoring: preferences, relative price and data confidence (see scoring.py).
    If nothing matched fully, the closest products are scored and returned instead, marked near_miss."""
    candidates = state["candidates"]
    if not candidates and state.get("dropped") and settings.closest_matches > 0:
        candidates = closest_matches(state["dropped"], settings.closest_matches)
        if candidates:
            emit("rank", "running", f"No exact matches: showing the {len(candidates)} closest")
    scored = scoring.score_products(state["criteria"], candidates)
    for p in scored:  # a closest match loses points for each thing it misses
        if p.get("near_miss"):
            p["match_score"] = max(0.0, round(p["match_score"] - NEAR_MISS_PENALTY * len(p["misses"]), 1))
    return {"candidates": scored}
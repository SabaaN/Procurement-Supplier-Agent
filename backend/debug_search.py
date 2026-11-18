"""Prints everything needed to see why a search found few or no products.

    python debug_search.py              # the most recent search
    python debug_search.py <search-id>  # a specific one

Reads only the local database (backend/data/app.db); prints no API keys.
It replays the budget and requirement checks on the products extracted in the last 24 hours,
so you can see, product by product, why each one was kept or dropped.
"""
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.graph import nodes
from app.services import extractor

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # product titles on Windows consoles


def short(text, n=60):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def main():
    db = sqlite3.connect(settings.db_path)
    if len(sys.argv) > 1:
        row = db.execute("SELECT id, device_type, criteria, status, error, created_at FROM searches WHERE id = ?", (sys.argv[1],)).fetchone()
    else:
        row = db.execute("SELECT id, device_type, criteria, status, error, created_at FROM searches ORDER BY created_at DESC LIMIT 1").fetchone()
    if row is None:
        sys.exit("No search found.")
    sid, device, raw_criteria, status, error, created = row

    print(f"== Search {sid}  ({device}, {status}{', error: ' + error if error else ''}, started {created})")
    print("\n== What you asked for")
    print(json.dumps(json.loads(raw_criteria), indent=2))

    print("\n== Progress events")
    for (event,) in db.execute("SELECT event FROM search_events WHERE search_id = ? ORDER BY seq", (sid,)):
        e = json.loads(event)
        print(f"  [{e.get('step')}/{e.get('status')}] {e.get('message')}")

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    print("\n== Pages downloaded in the last 24 hours")
    pages = db.execute("SELECT ok, error FROM page_cache WHERE fetched_at >= ?", (cutoff,)).fetchall()
    print(f"  {sum(ok for ok, _ in pages)} read OK, {sum(1 for ok, _ in pages if not ok)} failed")
    for reason, n in Counter(err for ok, err in pages if not ok).most_common(8):
        print(f"    {n} x {reason}")

    rows = db.execute(
        "SELECT url, product, kind FROM extraction_cache WHERE device_type = ? AND fetched_at >= ?",
        (extractor.cache_key(device), cutoff),
    ).fetchall()
    products = [json.loads(p) for _, p, _ in rows if p]
    kinds = Counter(kind or "other" for _, _, kind in rows)
    print(f"\n== Pages the model read in the last 24 hours: {len(rows)}")
    for kind, label in [("product", "product pages"), ("listing", "listing pages (product links followed)"),
                        ("wrong_type", "wrong kind of product (e.g. CCTV)"), ("other", "not product pages")]:
        print(f"  {kinds[kind]} {label}")

    if not products:
        print("  (none: nothing reached the filter. Look at the Search and Extract events above.)")
        return

    state = nodes.parse_requirements({"device_type": device, "raw_criteria": json.loads(raw_criteria)})
    if state.get("error"):
        sys.exit(f"Criteria did not parse: {state['error']}")
    state["products"] = products
    try:
        state.update(nodes.convert_prices(state))
    except Exception as e:  # e.g. no internet for exchange rates
        print(f"  (could not convert currencies: {e})")
    from app.devices import get_device
    device_checks = get_device(device).checks
    out = nodes.filter_products(state)
    reasons = {d["title"]: "; ".join(d["reasons"]) for d in out["dropped"]}

    print("\n== Replaying the filter on those products (with the current code and settings)")
    print(f"  strict_requirements={settings.strict_requirements}, max_pages_per_attempt={settings.max_pages_per_attempt}")
    for p in state["products"]:
        verdict = "DROPPED: " + reasons[p.get("title")] if p.get("title") in reasons else "kept"
        price = f"{p.get('price')} {p.get('currency') or '?'}"
        if p.get("price_buyer") is not None and p.get("currency") != state["criteria"].get("currency"):
            price += f" (= {p['price_buyer']:,.0f} {state['criteria'].get('currency')})"
        specs = " | ".join(f"{label}: {p.get(f) if not isinstance(f, tuple) else '-'.join(str(p.get(x)) for x in f)}"
                           for f, _cmp, label in device_checks.values())
        print(f"  - {short(p.get('title'))}\n      price {price} | {specs}"
              f"\n      {verdict}\n      {p.get('source_url')}")
    print(f"\n  {len(out['candidates'])} of {len(products)} would be kept now.")


if __name__ == "__main__":
    main()

"""Run one camera search through the graph and print progress + results.

    python run_demo.py
"""
import uuid

from app.graph.build import build_graph

graph = build_graph()

search_id = str(uuid.uuid4())
config = {"configurable": {"thread_id": search_id}}
inputs = {
    "search_id": search_id,
    "device_type": "camera",
    "raw_criteria": {
        "min_megapixels": {"value": 5, "required": True},
        "min_fps": {"value": 30, "required": False},
        "shutter": {"value": "global", "required": True},
        "interface": {"value": ["GigE", "USB3"], "required": False},
        "budget_max": 20000,
        "currency": "PKR",
        "quantity": 4,
    },
}

# "custom" mode delivers the progress events our nodes emit.
for *_, event in graph.stream(inputs, config, stream_mode=["custom"], subgraphs=True):
    print(f"[{event['step']:<8}] {event['status']:<7} {event['message']}")

final = graph.get_state(config).values
print("\nerror:", final.get("error"))
print("attempts:", final.get("attempts"))
print("queries tried:", *final.get("past_queries", []), sep="\n  ")
print(f"urls found: {len(final.get('urls', []))}")
for p in final.get("ranked", []):
    cur = p.get("currency") or ""
    price = f"{p['price']:,.2f} {cur}" if p.get("price") is not None else "price n/a"
    if p.get("fx_rate"):
        price += f"  (= {p['price_buyer']:,.0f} PKR at {p['fx_rate']})"
    print(f"\n{p['title'][:60]}   score {p['match_score']}  {p['score_breakdown']}")
    print(f"  {price} | {p.get('megapixels')} MP | {p.get('fps')} fps | {p.get('shutter')} shutter | {p.get('interface')}")
    if p.get("total_cost") is not None:
        print(f"  total for {inputs['raw_criteria']['quantity']}: {p['total_cost']:,.0f} PKR (excl. shipping and duties)")
    print(f"  met: {p['requirements_met']}  missed: {p['requirements_missed']}")
    print(f"  flags: {p['flags']}")
    print(f"  {p['source_url']}")

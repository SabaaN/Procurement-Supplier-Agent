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
for mode, event in graph.stream(inputs, config, stream_mode=["custom"], subgraphs=False):
    print(f"[{event['step']:<8}] {event['status']:<7} {event['message']}")

final = graph.get_state(config).values
print("\nerror:", final.get("error"))
print("attempts:", final.get("attempts"))
for p in final.get("ranked", []):
    print(f"  {p['title']:<16} {p['price']:>8} {p['currency']}  {p['megapixels']} MP  score={p['match_score']}")

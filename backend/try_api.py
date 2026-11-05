"""Start a search through the running API and print the live progress.

Terminal 1:  uvicorn app.main:app --reload
Terminal 2:  python try_api.py
"""
import json

import httpx

BASE = "http://127.0.0.1:8000"
body = {
    "device_type": "camera",
    "criteria": {
        "min_megapixels": {"value": 5, "required": True},
        "shutter": {"value": "global", "required": True},
        "interface": {"value": ["GigE", "USB3"], "required": False},
        "budget_max": 500000,
        "currency": "PKR",
        "quantity": 4,
    },
}

r = httpx.post(f"{BASE}/api/searches", json=body)
r.raise_for_status()
search_id = r.json()["id"]
print("search id:", search_id)

with httpx.stream("GET", f"{BASE}/api/searches/{search_id}/stream", timeout=None) as stream:
    event = None
    for line in stream.iter_lines():
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data = json.loads(line.split(":", 1)[1])
            if event == "progress":
                print(f"[{data['step']:<8}] {data['status']:<7} {data['message']}")
            else:
                print("END:", data)

results = httpx.get(f"{BASE}/api/searches/{search_id}/results").json()
for p in results["products"]:
    print(p["rank"], p["title"][:50], p["match_score"])
print(f"\nCSV: {BASE}/api/searches/{search_id}/export.csv")